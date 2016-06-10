
Printd
======

Printd is a background service that allows to print PDF files from anywhere on
your local printer by just sending an email.

It holds an IMAP client connection to a dedicated mailbox and tries to print
all PDF-attachments in incoming emails. If you send it an email with a subject
of "help" it will reply with more detailed instructions.

It does not need to run all the time, as it will also print any unread email
upon startup even if printd wasn't running at the time the email arrived.

It was originally written for a Raspberry Pi running OSMC but should easily
be portable to other platforms.


Quickstart
==========

1) Setup a default printer in CUPS.
2) Get a dedicated mailbox that supports IMAP, STARTTLS and IMAP IDLE for your print service.
3) Install the dependencies: try `sudo make deps`.
4) Install printd: try `sudo make install`.
5) Adapt the configuration in /etc/printd.conf to your setup and needs.
6) Enable and start printd: `systemctl enable printd.service && systemctl start printd.service`.
7) Happy printing! :)


Printer
=======

You need to have a default printer in your CUPS setup.

To install a HP AIO model, follow approximately these steps:
1) sudo apt-get install cups snmp-mibs-downloader printer-driver-all
2) sudo usermod -a -G lp,lpadmin osmc
3) Install newest HPLIP from http://hplipopensource.com/hplip-web/gethplip.html
4) sudo hp-setup -i $PRINTER_IP
5) sudo lpoptions -d $PRINTER_NAME
6) sudo nano /etc/cups/cupsd.conf   Give web-access to yourself
7) sudo systemctl enable cups && sudo systemctl start cups

NOTES:
- Without HPLIP you can install a printer using lpadmin -p $PRINTER_NAME -E -v $PRINTER_URI -m $PRINTER_PPD_FILE
  See CUPS-docs how to form the PRINTER_URI.
- Despite all the warnings, you might have to start the HPLIP-installer using 'sudo', since it uses 'su' to get root permissions,
  which does not work if there is no root-password.


MAIL-SERVER
===========

Your IMAP-server currently must support STARTTLS on default port 143 as well as RFC 2177 ( IMAP4 IDLE ).
Your SMTP-server must support STARTTLS on default port 25.



# vim:ft=rst:
