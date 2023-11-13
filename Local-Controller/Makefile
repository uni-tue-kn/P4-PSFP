all: compile start
	@echo "done"

start:
	./controller.py

compile:
	cd ../ && make compile

kill:
	sudo killall bf_switchd

sync:
	rsync -av ./ carrie:/home/ihlef/2022-msc-ihle-p4-psfp/Local-Controller
