#!/usr/bin/env python
"""A command line Podcast downloader for RSS XML feeds.

Usage:
    PodGrab.py --subscribe <feed_url>
    PodGrab.py --update
    PodGrab.py --help

Options:
    -d --download=<feed_url>            Bulk download all podcasts 
                                            in the following XML feed or file
    -e --export=<OPML_EXPORT>           Export subscriptions to OPML file
    -i --import=<opml_import>           Import subscriptions from OPML file
    -r --remove=<feed_url>              Remove from the Podcast feed
    -s --subscribe=<feed_url>           Subscribe to the XML feed 
                                            and download latest podcast
    -u --update                         Updates all current subscriptions

"""

# -m --mail-add=<mail_address>        Add a mail address to 
#    --mail-delete=<mail_address>        Delete a mail address
#    -l --list=<ALL> list_subs           Lists current Podcast subscriptions
#                                            Podcast subscriptions
#    -m --mail-list=<MAIL> list_mail     Lists all current mail addresses

#PodGrab - A Python command line audio/video podcast downloader for RSS XML feeds.
#Supported RSS item file types: MP3, M4V, OGG, FLV, MP4, MPG/MPEG, WMA, WMV, WEBM
#Version: 1.1.1 - 25/08/2011
#Jonathan Baker 
#jon@the-node.org http://the-node.org
#
#Some updates by Edward Delaporte http://edward.delaporte.us
#edthedev@gmail.com
#
#Outstanding issues:-
#- Video podcasts which which are not direct URLs and are modified by PodGrab
#  in order to be grabbed won't display their size as the filenames haven't 
#  been stripped of their garbage URL info yet. It'll say 0 bytes, but don't 
#  worry, they've downloaded. 

# DocOpt is awesome. https://github.com/docopt/docopt
from docopt import docopt
args = docopt(__doc__, version='1.0')
print args

import traceback
import os
import sys
import argparse
import urllib2
import xml.dom.minidom
import datetime
from time import gmtime, strftime, strptime, mktime
import sqlite3
import shutil
import smtplib
from email.mime.text import MIMEText
import platform
import traceback
import unicodedata
import socket
import errno

today = datetime.date.today()

MODE_NONE = 70
MODE_SUBSCRIBE = 71
MODE_DOWNLOAD = 72
MODE_UNSUBSCRIBE = 73
MODE_LIST = 74
MODE_UPDATE = 75
MODE_MAIL_ADD = 76
MODE_MAIL_DELETE = 77
MODE_MAIL_LIST = 78
MODE_EXPORT = 79
MODE_IMPORT = 80


DOWNLOAD_DIRECTORY = "podcasts"

total_item = 0
total_size = 0
has_error = 0

class RSSItem(object):
    """ Parse RSS feed item details from the XML"""
    def __init__(self, item_xml):
        """ Parse the xml. """
        self.title =  \
            item_xml.getElementsByTagName('title')[0].firstChild.data
        self.date = to_date(
            item_xml.getElementsByTagName(
                    'pubDate')[0].firstChild.data)
        self.url = item_xml.getElementsByTagName(
            'enclosure')[0].getAttribute('url')
        self.size = item_xml.getElementsByTagName(
            'enclosure')[0].getAttribute('length')
        self.filetype = item_xml.getElementsByTagName(
            'enclosure')[0].getAttribute('type')
    def __str__(self):
        return """Title: {title}
                Date: {date} 
                File URL: {url}
                Type: {filetype}
                Size: {size} bytes
            """.format(**self.__dict__)

class PodCasts(object):
    """Handle the podcasts."""

    def update_subscription(self, feed, date):
        """Update last downloaded date for the feed."""
        row = (date, feed)
        self.cur.execute('UPDATE subscriptions SET last_ep = ? where feed = ?', row)
        self.conn.commit()
        return True

    def __del__(self):
        """Cleanup database connection."""
        if self.conn:
            self.conn.close()

    def __init__(self):
        """Setup storage and database connection."""

        self.data_dir = os.path.expanduser('~/podcasts')

        # print "Default encoding: " + sys.getdefaultencoding()
        # current_directory = os.path.realpath(os.path.dirname(sys.argv[0]))
        self.current_directory = os.path.expanduser('~/')
        # print "Current Directory: ", self.current_directory

        self.conn = None

        self.db_file = os.path.join(self.data_dir, "PodGrab.db")

        new_database = False
        if not os.path.exists(self.db_file):
            new_database = True
            print "PodGrab database missing. Creating..."

        self.conn = sqlite3.connect(self.db_file)
        if not self.conn:
            print "Could not create PodGrab database file!"
            sys.exit(1)

        self.cur = self.conn.cursor()

        if new_database:
            print "Creating PodGrab database"
            self.cur.execute("CREATE TABLE subscriptions (channel text, feed text, last_ep text)")
            self.cur.execute("CREATE TABLE email (address text)")
            self.conn.commit()

            print "Database setup complete"

        if not os.path.exists(self.data_dir):
            print "Podcast download directory is missing. Creating..."
            try:
                os.mkdir(self.data_dir)
                print "Download directory '" + self.data_dir + "' created"
            except OSError:
                error_string = \
                    ("Could not create podcast download sub-directory:" 
                    "{dir}!").format(dir=self.data_dir)
                print error_string
                sys.exit(1)
        else:
            print "Download directory exists: '" + self.data_dir + "'" 

    def get_subscriptions(self):
        try:
            self.cur.execute('SELECT channel, feed, last_ep FROM subscriptions')
            return self.cur.fetchall()
        except sqlite3.OperationalError as exc:
            print "There are no current subscriptions"
            return [] 

    def subscribe(self, feed_url):
        """Subscribe to a feed by URL"""
        channels = self.get_channels(feed_url)
        for channel in channels:

            channel_title = channel.getElementsByTagName('title')[0].firstChild.data
            channel_link = channel.getElementsByTagName('link')[0].firstChild.data
            print "Channel Title: ===" + channel_title + "==="
            print "Channel Link: " + channel_link

            channel_title = clean_string(channel_title)
            channel_directory = self._get_channel_directory(channel_title)

            if does_sub_exist(self.cur, self.conn, feed_url):
                print "Podcast subscription exists - getting latest podcast"
                last_ep = get_last_subscription_downloaded(self.cur, self.conn, feed_url)
            else:
                print "Podcast subscription is new - getting previous podcast"
                return self.insert_subscription(
                    channel.getElementsByTagName('title')[0].firstChild.data, feed_url)

    def get_channels(self, feed_url):
        """Get a list of channels in the feed."""
        xml_data = open_datasource(feed_url)
        if not xml_data:
            error_string = "Not a valid XML file or URL feed!"
            print error_string
            sys.exit(1)
        # print "XML data source opened\n"

        channel_data = xml.dom.minidom.parseString(xml_data)
        channels = channel_data.getElementsByTagName('channel')
        return channels

    def insert_subscription(self, chan, feed):
        chan.replace(' ', '-')
        chan.replace('---','-')
        row = (chan, feed, "NULL")
        self.cur.execute('INSERT INTO subscriptions(channel, feed, last_ep) VALUES (?, ?, ?)', row)
        self.conn.commit()
        return True

    def _update_channel(self, channel_data, feed, last_updated):
        """Download the channel within the feed."""
        global total_items
        global total_size
        NUM_MAX_DOWNLOADS = 4
        saved = 0
        num = 0
        size = 0
        last_ep = "NULL"
        today = datetime.date.today()

        channel_title = channel_data.getElementsByTagName('title')[0].firstChild.data
        print u"Checking {title} for updates.".format(title=channel_title)
        chan_dir = self._get_channel_directory(channel_title)

        for item_xml in channel_data.getElementsByTagName('item'):
            try:
                item = RSSItem(item_xml)
                struct_time_today = today
                saved = 0
                has_error = 0    
                try:
                    if item.date <= datetime.datetime.today() \
                            and item.date >= last_updated:
                        print u"Downloading {title}".format(title=item.title)
                        saved = write_podcast(item, chan_dir)
                    if saved > 0:
                        print "Downloading:\n {item}".format(item = str(item)) 
                        num = num + saved
                        size = size + int(item.size)
                        total_size += size
                        total_items += num
                        self.update_subscription(feed, item.date)

                except TypeError as exc:
                    print traceback.format_exc()
                    print "Unable to parse date. Bad type. {date}".format(item_date)
                    has_error = 1
                except ValueError:
                    has_error = 1
                    print "Unable to parse date. Bad value. {date}".format(item_date)

                if (num >= NUM_MAX_DOWNLOADS):
                    print "Maximum session download of " + str(NUM_MAX_DOWNLOADS) + " podcasts has been reached. Exiting."
                    break

            except IndexError, e:
                #traceback.print_exc()
                print "This RSS item has no downloadable URL link for the podcast for '" + item_title  + "'. Skipping..."
            # except AttributeError as exc:
            #    print "This RSS item appears to have no data attribute for the podcast '" + item_title + "'. Skipping..." 
        return str(num) + " podcasts totalling " + str(size) + " bytes"

    def _get_channel_directory(self, channel_title):
        """Return the directory for the channel.

        Ensure that it exists."""
        channel_directory  = os.path.join(self.data_dir, channel_title)
        if not os.path.exists(channel_directory):
            os.makedirs(channel_directory)
        return channel_directory

    def _iterate_feed(self, data, mode, feed):
        """Work through a PodCast XML feed."""

        today = datetime.date.today()
        print "Iterating feed..."
        message = ""
        try:
            xml_data = xml.dom.minidom.parseString(data)
            for channel in xml_data.getElementsByTagName('channel'):
                channel_title = channel.getElementsByTagName('title')[0].firstChild.data
                channel_link = channel.getElementsByTagName('link')[0].firstChild.data
                print "Channel Title: ===" + channel_title + "==="
                print "Channel Link: " + channel_link

                channel_title = clean_string(channel_title)
                channel_directory = self._get_channel_directory(channel_title)

                if mode == MODE_DOWNLOAD:
                    print "Bulk download. Processing..."
                    num_podcasts = self.iterate_channel(channel, today, 
                            mode, feed, channel_directory)
                    print "\n", num_podcasts, "have been downloaded"
                elif mode == MODE_SUBSCRIBE:
                    print "Feed to subscribe to: " + feed + ". Checking for database duplicate..."
                    if not does_sub_exist(self.cur, self.conn, feed):
                        print "Subscribe. Processing..."
                        num_podcasts = self.iterate_channel(channel, today, 
                                mode, feed, channel_directory)
                        print "\n", num_podcasts, "have been downloaded from your subscription"
                    else:
                        print "Subscription already exists! Skipping..."
                elif mode == MODE_UPDATE:
                    print "Updating RSS feeds. Processing..."
                    num_podcasts = self.iterate_channel(channel, today, 
                            mode, feed, channel_directory)
                    message += str(num_podcasts) + " have been downloaded from your subscription: '" + channel_title + "'\n"
        except xml.parsers.expat.ExpatError:
            print "ERROR - Malformed XML syntax in feed. Skipping..."
            message += "0 podcasts have been downloaded from this feed due to RSS syntax problems. Please try again later"
        except UnicodeEncodeError:
            print "ERROR - Unicoce encoding error in string. Cannot convert to ASCII. Skipping..."
            message += "0 podcasts have been downloaded from this feed due to RSS syntax problems. Please try again later"
        return message

    def update_feed(self, feed_name, feed_url, last_updated):
        """Update all channels in a feed."""

        print "Updating feed {name}...".format(name=feed_name)
        # print "Feed for subscription: '" + feed_name + \
        #        "' from '" + feed_url + "' is updating..."

        channels = self.get_channels(feed_url)
        for channel in channels:
            self._update_channel(channel, feed_url, last_updated)
        print "Finished updating feed {name}".format(name=feed_name)

    def update_all(self):
        """Update all podcast subscriptions."""

        print "Updating all podcast subscriptions..."
        subs = self.get_subscriptions()
        if len(subs) == 0:
            print "No subscriptions."

        for sub in subs:
            feed_name = sub[0]
            feed_url = sub[1]
            feed_name.encode('utf-8')
            feed_url.encode('utf-8')

            feed_last_updated = datetime.datetime.today() - \
                datetime.timedelta(days=7)

            if sub[2] != 'NULL':
                feed_last_updated = to_date(sub[2])

            message = self.update_feed(feed_name, feed_url, feed_last_updated)
            print message

# TODO: Re-enable mail later
        #        mail += message
        #mail = mail + "\n\n" + str(total_items) + " podcasts totalling " + str(total_size) + " bytes have been downloaded."

#       if has_mail_users(cursor, connection):
#            print "Have e-mail address(es) - attempting e-mail..."
#            mail_updates(cursor, connection, mail, str(total_items))

def main():
    mode = MODE_NONE
    has_error = 0
    num_podcasts = 0
    error_string = ""
    feed_url = ""
    feed_name = ""
    mail_address = ""
    message = ""
    mail = ""
    global total_items
    global total_size
    total_items = 0
    total_size = 0
    data = ""

    parser = argparse.ArgumentParser(description='A command line Podcast downloader for RSS XML feeds')
    parser.add_argument('-s', '--subscribe', action="store", dest="sub_feed_url", help='Subscribe to the following XML feed and download latest podcast')
    parser.add_argument('-d', '--download', action="store", dest="dl_feed_url", help='Bulk download all podcasts in the following XML feed or file')
    parser.add_argument('-un', '--unsubscribe', action="store", dest="unsub_url", help='Unsubscribe from the following Podcast feed')
    parser.add_argument('-ma', '--mail-add', action="store", dest="mail_address_add", help='Add a mail address to mail subscription updates to')
    parser.add_argument('-md', '--mail-delete', action="store", dest="mail_address_delete", help='Delete a mail address')

    parser.add_argument('-l', '--list', action="store_const", const="ALL", dest="list_subs", help='Lists current Podcast subscriptions')
    parser.add_argument('-u', '--update', action="store_const", const="UPDATE", dest="update_subs", help='Updates all current Podcast subscriptions')
    parser.add_argument('-ml', '--mail-list', action="store_const", const="MAIL", dest="list_mail", help='Lists all current mail addresses')

    parser.add_argument('-io', '--import', action="store", dest="opml_import", help='Import subscriptions from OPML file')
    parser.add_argument('-eo', '--export', action="store_const", const="OPML_EXPORT", dest="opml_export", help='Export subscriptions to OPML file')
    
    arguments = parser.parse_args()

    todays_date = strftime("%a, %d %b %Y %H:%M:%S", gmtime())

    pc = PodCasts()

    if args['--subscribe']:
        feed_url = args['--subscribe']
        
        # mode = MODE_SUBSCRIBE
        result = pc.subscribe(feed_url)
        # result = pc._iterate_feed(data, mode, feed_url)
        print result

    if args['--update']:
        pc.update_all()

    if arguments.dl_feed_url:
        feed_url = arguments.dl_feed_url
        data = open_datasource(feed_url)
        if not data:
            error_string = "Not a valid XML file or URL feed!"
            has_error = 1 
        else:
            print "XML data source opened\n"
            mode = MODE_DOWNLOAD
    elif arguments.unsub_url:
        feed_url = arguments.unsub_url
        mode = MODE_UNSUBSCRIBE
    elif arguments.list_subs:
        mode = MODE_LIST
    elif arguments.update_subs:
        mode = MODE_UPDATE
    elif arguments.mail_address_add:
        mail_address = arguments.mail_address_add
        mode = MODE_MAIL_ADD
    elif arguments.mail_address_delete:
        mail_address = arguments.mail_address_delete
        mode = MODE_MAIL_DELETE
    elif arguments.list_mail:
        mode = MODE_MAIL_LIST
    elif arguments.opml_import:
        import_file_name = arguments.opml_import
        mode = MODE_IMPORT
    elif arguments.opml_export:
        mode = MODE_EXPORT
    else:
        error_string = "No Arguments supplied - for usage run 'PodGrab.py -h'"
        has_error = 1

    if not has_error:
        if mode == MODE_UNSUBSCRIBE:
            feed_name = get_name_from_feed(cursor, connection, feed_url)
            if feed_name == "None":
                print "Feed does not exist in the database! Skipping..."
            else:
                feed_name = clean_string(feed_name)
                channel_directory = download_directory + os.sep + feed_name
                print "Deleting '" + channel_directory + "'..."
                delete_subscription(cursor, connection, feed_url)
                try :
                    shutil.rmtree(channel_directory)
                except OSError:
                    print "Subscription directory has not been found - it might have been manually deleted" 
                print "Subscription '" + feed_name + "' removed"
        elif mode == MODE_LIST:
            print "Listing current podcast subscriptions...\n"
            list_subscriptions(cursor, connection)
        elif mode == MODE_MAIL_ADD:
            add_mail_user(cursor, connection, mail_address)
            print "E-Mail address: " + mail_address + " has been added"
        elif mode == MODE_MAIL_DELETE:
            delete_mail_user(cursor, connection, mail_address)
            print "E-Mail address: " + mailAddress + " has been deleted"
        elif mode == MODE_MAIL_LIST:
            list_mail_addresses(cursor, connection)
        elif mode == MODE_EXPORT:
            export_opml_file(cursor, connection, current_directory)
        elif mode == MODE_IMPORT:
            import_opml_file(cursor, connection, current_directory, download_directory, import_file_name)
    else:
        print "Sorry, there was some sort of error: '" + error_string + "'\nExiting...\n"

def to_date(date_string):
    formats = [
        "%a, %d %b %Y %H:%M:%S",
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S -0400",
        "%Y-%m-%d %H:%M:%S",
            ]
    for form in formats:
        try:
            return datetime.datetime.strptime(date_string, form)
        except:
            # print "Date {date} did not match {form}.".format(
              #      date=date_string, form=form)
            pass

    raise Exception("Unrecognized date: {date}".format(date=date_string))

def open_datasource(xml_url):
    print "Opening feed {url}".format(url=xml_url)
    try:
        response = urllib2.urlopen(xml_url)
    except ValueError:
        try:
            response = open(xml_url,'r')
        except ValueError:
            print "ERROR - Invalid feed!"
            response = False
        except urllib2.URLError:
            print "ERROR - Connection problems. Please try again later"
            response = False
#        except httplib.IncompleteRead:
#            print "ERROR - Incomplete data read. Please try again later"
#            response = False

    if response != False:
        return response.read()
    else:
        return response

def export_opml_file(cur, conn, cur_dir):
    item_count = 0
    feed_name = ""
    feed_url = ""
    last_ep = ""
    now = datetime.datetime.now()
    file_name = cur_dir + os.sep + "podgrab_subscriptions-" + str(now.year) + "-" + str(now.month) + "-" + str(now.day) + ".opml"
    subs = get_subscriptions(cur, conn)
    file_handle = open(file_name,"w")
    print "Exporting RSS subscriptions database to: '" + file_name + "' OPML file...please wait.\n"
    header = "<opml version=\"2.0\">\n<head>\n\t<title>PodGrab Subscriptions</title>\n</head>\n<body>\n"
    file_handle.writelines(header)
    for sub in subs:
        feed_name = sub[0]
        feed_url = sub[1]
        last_ep = sub[2]
        file_handle.writelines("\t<outline title=\"" + feed_name + "\" text=\"" + feed_name + "\" type=\"rss\" xmlUrl=\"" + feed_url + "\" htmlUrl=\"" + feed_url + "\"/>\n")
        print "Exporting subscription '" + feed_name + "'...Done.\n"
        item_count = item_count + 1
    footer = "</body>\n</opml>"
    file_handle.writelines(footer)
    file_handle.close()
    print str(item_count) + " item(s) exported to: '" + file_name + "'. COMPLETE"

def import_opml_file(cur, conn, cur_dir, download_dir, import_file):
    count = 0
    print "Importing OPML file '" + import_file + "'..."
    if import_file.startswith("/") or import_file.startswith(".."):
        data = open_datasource(import_file)
        if not data:
            print "ERROR = Could not open OPML file '" + import_file + "'"
    else:
        data = open_datasource(cur_dir + os.sep + import_file)
        if not data:
            print "ERROR - Could not open OPML file '" + cur_dir + os.sep + import_file + "'"
    if data:
        print "File opened...please wait"
        try:
            xml_data = xml.dom.minidom.parseString(data)
            items = xml_data.getElementsByTagName('outline')
            for item in items:
                item_feed = item.getAttribute('xmlUrl')
                item_name = item.getAttribute('title')
                item_name = clean_string(item_name)
                print "Subscription Title: " + item_name
                print "Subscription Feed: " + item_feed
                item_directory = download_dir + os.sep + item_name
            
                if not os.path.exists(item_directory):
                    os.makedirs(item_directory)
                if not does_sub_exist(cur, conn, item_feed):
                    self.insert_subscription(item_name, item_feed)
                    count = count + 1
                else:
                    print "This subscription is already present in the database. Skipping..."
                print "\n"
            print "\nA total of " + str(count) + " subscriptions have been added from OPML file: '" + import_file + "'"
            print "These will be updated on the next update run.\n"
        except xml.parsers.expat.ExpatError:
            print "ERROR - Malformed XML syntax in feed. Skipping..."

def clean_string(str):
    new_string = str
    if new_string.startswith("-"):
        new_string = new_string.lstrip("-")
    if new_string.endswith("-"):
        new_string = new_string.rstrip("-")
    new_string_final = ''
    for c in new_string:
        if c.isalnum() or c == "-" or c == "." or c.isspace():
            new_string_final = new_string_final + ''.join(c)
    new_string_final = new_string_final.strip()
    new_string_final = new_string_final.replace(' ','-')
    new_string_final = new_string_final.replace('---','-')
    new_string_final = new_string_final.replace('--','-')
    return new_string_final

def write_podcast(rss_item, chan_loc):
    (rss_item_path, rss_item_file_name) = os.path.split(rss_item.url)

    if len(rss_item_file_name) > 50:
        rss_item_file_name = rss_item_file_name[:50]
    today = datetime.date.today()
    rss_item_file_name = today.strftime("%Y/%m/%d") + rss_item_file_name
    local_file = chan_loc + os.sep + clean_string(rss_item_file_name)
    if rss_item.filetype == "video/quicktime" or rss_item.filetype == "audio/mp4" or rss_item.filetype == "video/mp4":
        if not local_file.endswith(".mp4"):
            local_file = local_file + ".mp4"
    elif rss_item.filetype == "video/mpeg":
                if not local_file.endswith(".mpg"):
                        local_file = local_file + ".mpg"
    elif rss_item.filetype == "video/x-flv":
        if not local_file.endswith(".flv"):
            local_file = local_file + ".flv"
    elif rss_item.filetype == "video/x-ms-wmv":
        if not local_file.endswith(".wmv"):
                        local_file = local_file + ".wmv"
    elif rss_item.filetype == "video/webm" or rss_item.filetype == "audio/webm":
        if not local_file.endswith(".webm"):
            local_file = local_file + ".webm"
    elif rss_item.filetype == "audio/mpeg":
                if not local_file.endswith(".mp3"):
                        local_file = local_file + ".mp3"
    elif rss_item.filetype == "audio/ogg" or rss_item.filetype == "video/ogg" or rss_item.filetype == "audio/vorbis":
                if not local_file.endswith(".ogg"):
                        local_file = local_file + ".ogg"
    elif rss_item.filetype == "audio/x-ms-wma" or rss_item.filetype == "audio/x-ms-wax":
        if not local_file.endswith(".wma"):
                        local_file = local_file + ".wma"    
    if os.path.exists(local_file):
        return 0
    else:
        print "\nDownloading {filename} which was published on {date}".format(
            filename = rss_item_file_name,
            date = rss_item.date)
        try:
            rss_item_file = urllib2.urlopen(rss_item.url)
            output = open(local_file, 'wb')
            output.write(rss_item_file.read())
            output.close()
            print "Podcast: ", rss_item, " downloaded to: ", local_file
            return 1
        except urllib2.URLError as e:
            print "ERROR - Could not write rss_item to file: ", e
        except socket.error as e:
            print "ERROR - Socket reset by peer: ", e



def add_mail_user(cur, conn, address):
    row = (address,)
    cur.execute('INSERT INTO email(address) VALUES (?)', row)
    conn.commit()


def delete_mail_user(cur, conn, address):
    row = (address,)
    cur.execute('DELETE FROM email WHERE address = ?', row)
    conn.commit()


def get_mail_users(cur, conn):
    cur.execute('SELECT address FROM email')
    return cur.fetchall()


def list_mail_addresses(cur, conn):
    cur.execute('SELECT * from email')
    result = cur.fetchall()
    print "Listing mail addresses..."
    for address in result:
        print "Address:\t" + address[0]


def has_mail_users(cur, conn):
    cur.execute('SELECT COUNT(*) FROM email')
    if cur.fetchone() == "0":
        return 0
    else:
        return 1


def mail_updates(cur, conn, mess, num_updates):
    addresses = get_mail_users(cur, conn)
    for address in addresses:
        try:
            subject_line = "PodGrab Update"
            if int(num_updates) > 0:
                subject_line += " - NEW updates!"
            else:
                subject_line += " - nothing new..."
            mail('localhost', 'podgrab@' + platform.node(), address[0], subject_line, mess)
            print "Successfully sent podcast updates e-mail to: " + address[0]
        except smtplib.SMTPException:
            traceback.print_exc()
            print "Could not send podcast updates e-mail to: " + address[0]


def mail(server_url=None, sender='', to='', subject='', text=''):
    headers = "From: %s\r\nTo: %s\r\nSubject: %s\r\n\r\n" % (sender, to, subject)
    message = headers + text
    mail_server = smtplib.SMTP(server_url)
    mail_server.sendmail(sender, to, message)
    mail_server.quit()    




def fix_date(date):
    new_date = ""
    split_array = date.split(' ')
    for i in range(0,5):
        new_date = new_date + split_array[i] + " "
    return new_date.rstrip()

def does_sub_exist(cur, conn, feed):
    row = (feed,)
    cur.execute('SELECT COUNT (*) FROM subscriptions WHERE feed = ?', row)
    return_string = str(cur.fetchone())[1]
    if return_string == "0":
        return 0
    else:
        return 1


def delete_subscription(cur, conn, url):
    row = (url,)
    cur.execute('DELETE FROM subscriptions WHERE feed = ?', row)
    conn.commit()


def get_name_from_feed(cur, conn, url):
    row = (url,)
    cur.execute('SELECT channel from subscriptions WHERE feed = ?', row)
    return_string = cur.fetchone()
    try:
        return_string = ''.join(return_string)
    except TypeError:
        return_string = "None"
    return str(return_string)


def list_subscriptions(cur, conn):
    count = 0
    try:
        result = cur.execute('SELECT * FROM subscriptions')
        for sub in result:
            print "Name:\t\t", sub[0]
            print "Feed:\t\t", sub[1]
            print "Last Ep:\t", sub[2], "\n"
            count += 1
        print str(count) + " subscriptions present"
    except sqlite3.OperationalError:
        print "There are no current subscriptions or there was an error"

def get_last_subscription_downloaded(cur, conn, feed):
    row = (feed,)
    cur.execute('SELECT last_ep FROM subscriptions WHERE feed = ?', row)
    return cur.fetchone()

if __name__ == "__main__":
    main()
