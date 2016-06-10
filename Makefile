
all:
	echo "Nothing to do"

install:
	[ -f /etc/printd.conf ] && mv /etc/printd.conf /etc/printd.conf.bak
	groups printd || useradd --system -M -U -G lp -s /bin/nologin printd
	install -m 755 -g root -o root printd.py /usr/local/lib/printd.py
	install -m 644 -g root -o root printd.service /lib/systemd/system/printd.service
	install -m 600 -g root -o printd printd.conf /etc/printd.conf

deps:
	-apt-get install python3-dev libffi-dev libssl-dev
	-pip3 install imapclient

enable:
	systemctl enable printd.service

package:
	tar -cvvzf printd.tgz Makefile README.txt printd.py printd.conf printd.service

clean:
	-rm printd.tgz
