CFLAGS=-D__STREAM_ID__=3 -D__STREAM_ID_SIZE__=4096 -D__STREAM_GATE_SIZE__=2048

all: compile start

compile:
	${SDE_INSTALL}/bin/bf-p4c --target tofino --arch tna -o /home/ihlef/2022-msc-ihle-p4-psfp/output sdn-psfp.p4
	cp /home/ihlef/2022-msc-ihle-p4-psfp/output/sdn-psfp.conf ${SDE_INSTALL}/share/p4/targets/tofino/sdn-psfp.conf

bench:
	${SDE_INSTALL}/bin/bf-p4c $(CFLAGS) --target tofino --arch tna -o /home/ihlef/2022-msc-ihle-p4-psfp/output sdn-psfp.p4
	cp /home/ihlef/2022-msc-ihle-p4-psfp/output/sdn-psfp.conf ${SDE_INSTALL}/share/p4/targets/tofino/sdn-psfp.conf

start:
	${SDE}/run_switchd.sh -p sdn-psfp

sync:
	rsync -av --exclude output/ ./ carrie:/home/ihlef/2022-msc-ihle-p4-psfp
