#!/usr/bin/env python3


# BEGIN INLINE udil.email.mailbot


import logging
import sys
import os
import os.path
import time
import datetime
import collections
import atexit
import traceback
import io
import email.message
import email.utils
import email.encoders
import email.mime
import email.mime.multipart
import email.mime.text
import email.mime.message
import email.mime.application
import email.mime.base
import mimetypes
import smtplib

import imapclient

logger = logging.getLogger(__name__)


Attachment = collections.namedtuple("Attachment", ('filename', 'data'))


class Mailbot:
    def __init__( self,
                  mailaddr = 'mailbot@example.com',
                  mailname = None, # e.g. 'Example Mailbot'
                  imaphost    ='imap.example.com',
                  imapusername='mailbot',
                  imappassword='password',
                  smtphost    ='smtp.example.com',
                  smtpusername=None,
                  smtppassword=None,
                  adminaddr = 'postmaster@example.com',
                  ssl       = 'starttls',
                  users     = {},
                  job       = None,
                  **kwargs
                 ):
        self.mailaddr = mailaddr
        self.mailname = mailname
        self.imaphost = imaphost
        self.imapusername = imapusername
        self.imappassword = imappassword
        self.smtphost = smtphost
        self.smtpusername = smtpusername or imapusername
        self.smtppassword = smtppassword or imappassword
        self.adminaddr = adminaddr
        self.ssl = ssl
        self.inbox = "INBOX"
        assert users
        self.users = users
        assert job
        self.jobFactory = job
        self.client = None
        for k in kwargs:
            logger.warning("Unused argument: %s", k)
        return


    # **********************************************
    # * mail server primitives

    def connect(self):
        self.disconnect()
        self.client = imapclient.IMAPClient(self.imaphost, port=None, use_uid=True)
        atexit.register(self.disconnect)
        ctx = imapclient.create_default_context()
        self.client.starttls(ssl_context=ctx)
        self.client.login(self.imapusername, self.imappassword)
        self.client.id_(None) # TODO: be nicer
        self.client.select_folder(self.inbox)

    def disconnect(self):
        if self.client:
            self.client.logout()
        self.client = None


    def sendmail(self, msg):
        msg['From'] = msg['From'] or email.utils.formataddr(( self.mailname, self.mailaddr ))
        msg['To']   = msg['To']   or self.adminaddr
        msg['Date'] = msg['Date'] or email.utils.format_datetime(datetime.datetime.now())
        if msg.get('Bcc', "") == "ADMIN":
            msg.replace_header('Bcc', self.adminaddr)
        with smtplib.SMTP(self.smtphost) as smtp:
            smtp.starttls()
            smtp.login(self.smtpusername, self.smtppassword)
            smtp.send_message(msg, to_addrs=msg.get_all('To', []) + msg.get_all('Cc', []) + msg.get_all('Bcc', []))


    # **********************************************
    # * mailbot implementation

    def mainloop(self):
        """ Keep connection working and collect incoming mails """
        while True:
            try:
                try:
                    self.connect()
                    logger.info('Connected...')
                except:
                    logger.warning('Connection failure. Retrying in 5 min')
                    time.sleep(5*60)
                    continue
                while True:
                    # NOTE: imapflags: b'\\Draft', b'\\Flagged', b'\\Answered', b'\\Seen', b'\\Deleted'
                    for uid in self.client.search([b'UNDELETED', b'UNSEEN']):
                        response = self.client.fetch([uid], [b'RFC822'])
                        self.client.add_flags( [uid], [b'\\Seen', b'\\Flagged'] )
                        raw = response[uid][b'RFC822']
                        mail = email.message_from_bytes(raw)
                        success = self.handle(mail)
                        if success:
                            self.client.remove_flags( [uid], [b'\\Flagged'] )
                    self.client.idle()
                    self.client.idle_check(25*60)
                    self.client.idle_done()
            except KeyboardInterrupt:
                return 0
            except Exception as e:
                logger.exception(str(e))
                continue
        return -1


    def handle(self, mail):
        """ Process a single incoming mail """
        _,sender = email.utils.parseaddr(mail.get('From'))
        if self.mailaddr in sender:
            return #NOTE: prevent loops
        if not self.authorized( mail ):
            msg = email.message.Message()
            msg['References'] = mail.get('Message-Id')
            msg['Subject'] = "[%s] Unauthorized attempt from %s" % ( self.jobFactory.PREFIX, sender )
            msg.set_payload("")
            logger.warning("Unauthorized attempt from %s", sender)
            return False
        # TODO: gpg decrypt
        log = io.StringIO()
        log_handler = logging.StreamHandler(log)
        log_handler.setLevel(logging.DEBUG)
        logging.getLogger("").addHandler(log_handler)
        try:
            job = self.jobFactory(mail)
            job.handle()
            logger.info("Job completed.")
            for m in job.replies:
                self.sendmail(m)
            return job.success
        except Exception as e:
            job.success = False
            text = "Leider is bei der Bearbeitung Ihrer Anfrage ein Fehler aufgetreten.\nBitte fragen sie Ihren Administrator.\n"
            msg = email.message.Message()
            msg['To']   = sender
            msg['References'] = mail.get('Message-Id')
            msg['Subject'] = 'Re: ' + mail.get('Subject', "")
            msg.set_payload(text)
            self.sendmail(msg)
            err  = str(e)
            tb   = traceback.format_exc()
            subject = "Fehler bei einer Anfrage von {sender}"
            fulltext = "%s\n\n%s\n\n%s" % (err, tb, log.getvalue())
            logger.debug(fulltext)
            msg = email.message.Message()
            msg['References'] = mail.get('Message-Id')
            msg['Subject'] = subject.format(sender=sender)
            msg.set_payload(fulltext)
            self.sendmail(msg)
        finally:
            logging.getLogger("").removeHandler(log_handler)


    def authorized(self, mail):
        """ Check if sender may use this service """
        _,sender = email.utils.parseaddr(mail.get('From'))
        if not sender:
            logger.info("No sender address")
            return False
        auth = self.users.get(sender)
        if auth is None:
            auth = self.users.get('ALL')
        if not auth:
            logger.info("Sender not authorized: %s", sender)
            return False
        elif auth is True:
            return True
        elif not isinstance(auth, str):
            return False
        elif auth.lower() in "1 true on yes".split():
            return True
        elif auth.lower() == 'dkim':
            dkim = email.utils.collapse_rfc2231_value( mail.get_param("dkim", '', "Authentication-Results") )
            if dkim == "pass":
                return True
            else:
                logger.debug("Could not verify sender %s via DKIM. Result: %s", sender, dkim or '<None>')
                return False
        return False


class Job:
    PREFIX = '[BOT] '

    def __init__(self, mail):
        self.mail = mail
        self.sender = email.utils.parseaddr(mail.get('From'))[1]
        self.subject = mail.get('Subject', "")
        self.msgid = mail.get('Message-Id')
        self.success = False
        self.replies = []
        self.init()

    # ***********************************************
    # * deferred responses

    def adminmail(self, subject, text):
        """ Notify admin deferred """
        msg = email.message.Message()
        msg['References'] = self.msgid
        msg['Subject'] = self.PREFIX + subject.format(sender=self.sender, subject=self.subject)
        msg.set_payload(text)
        logger.warning("Error: %s", text[:80])
        self.replies.append( msg )


    def response(self, text, attachments=[], Bcc=True):
        """ Reply to user deferred """
        msg = email.mime.multipart.MIMEMultipart()
        msg['To']   = self.sender
        if Bcc:
            msg['Bcc']  = "ADMIN"
        msg['References'] = self.msgid
        msg['Subject'] = 'Re: ' + self.subject
        if True:
            m = email.mime.text.MIMEText(text, _subtype='plain')
            m.add_header('Content-Disposition', 'inline')
            msg.attach(m)
        for a in attachments:
            if isinstance(a, str):
                a = Attachment(a, None)
            logger.debug("attaching %s ...", a.filename)
            if a.data:
                data = a.data
            elif os.path.isfile(a.filename):
                with open(a.filename, 'rb') as f:
                    data = f.read()
            else:
                logger.error("No data for file %s", a.filename)
                continue
            filename = os.path.basename(a.filename)
            ctype,encoding = mimetypes.guess_type(filename)
            if ctype is None or encoding:
                ctype = 'application/octet-stream'
            maintype,_,subtype = ctype.partition('/')
            m = email.mime.base.MIMEBase(maintype,subtype)
            m.set_payload(data)
            email.encoders.encode_base64(m)
            m.add_header('Content-Disposition', 'attachment', filename=filename)
            msg.attach(m)
        self.replies.append( msg )


    # ***********************************************
    # * job specific init

    def init(self):
        pass

    # ***********************************************
    # * worker

    def handle(self):
        """ Do the implementation dance """
        raise NotImplementedError()
        self.success = True
        return




# END INLINE udil.email.mailbot




# *********************************************************
# *
# *  Actual implementation starts here
# *
# *********************************************************

import subprocess
import shlex
import configparser


HELP_TEXT = """

Print files to CUPS default printer.

Currently only PDF files given as attachments are printed.
A subject of "help" will be replied to with this help text.

Options can be given in any text/plain part of the mail, they are forwarded verbatim to "lp".
Examples:
    -n N            Print N copies
    -H HH:MM        Print at the specified time.
    -P RANGE        Print the specified range of pages, e.g. 1,3-5,16
    -o media=SIZE   Print in a4 or letter or legal...
    -o fit-to-page  Scale to fit the page.
    -o number-up=N  Print N pages per sheet. Possible values: 2,4,6,9,16

"""



class PrintJob(Job):
    PREFIX = '[PRINT] '

    def init(self):
        self.help = False
        self.files = []
        self.opts = []


    # ***********************************************
    # * worker

    def handle(self):
        """ Process a single mail """
        logger.debug("New job from %s", self.sender)
        self.parse()
        if self.help:
            logger.debug("Requested help")
            self.response(HELP_TEXT, Bcc=False)
        self.lpr()
        self.success = True


    def parse(self):
        """ Unpack Message object """
        if self.mail.get('Subject', '').lower() == 'help':
            self.help = True
        for part in self.mail.walk():
            if part.get_content_maintype() == 'multipart':
                continue
            filename = part.get_filename() or mimetypes.guess_extension(part.get_content_type()) or 'unknown.bin'
            _,_,ext = filename.rpartition('.')
            if ext == 'txt':
                try:
                    for line in part.get_payload(decode=True).decode('utf-8').splitlines():
                        line = line.strip()
                        if line.lstrip('-').lower() == 'help':
                            self.help = True
                        elif line.startswith('---'):
                            break
                        elif line.startswith('-'):
                            self.opts.extend( shlex.split(line) )
                except Exception as e:
                    logger.debug('Parsing error: %s', str(e), exc_info=True)
            elif ext == 'pdf':
                self.files.append( Attachment(filename, part.get_payload(decode=True)) )
        return

    def lpr(self):
        """ Print the attached files """
        for file in self.files:
            logger.debug("Printing file: %s", file.filename)
            p = subprocess.Popen(['lp', '-t', file.filename] + self.opts + ['--', '-'], stdin=subprocess.PIPE)
            p.communicate(file.data)
        return


def main():
    logging.basicConfig(level=logging.DEBUG)
    configfile = os.environ.get('PRINTD_CONFIG', '/etc/printd.conf')
    config = configparser.ConfigParser()
    config['DEFAULT'] = {
        'mailname' : 'Print'
    }
    config.read(configfile)
    cfg   = config['printd']
    users = config['users']
    mb = Mailbot( job=PrintJob, users=users, **cfg )
    return mb.mainloop()


if __name__ == '__main__':
    main()

