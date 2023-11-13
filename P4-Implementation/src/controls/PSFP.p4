#include "StreamFilter.p4"
#include "StreamGate.p4"
#include "FlowMeter.p4"

control PSFP(inout header_t hdr, 
            inout ingress_metadata_t ig_md, 
            inout ingress_intrinsic_metadata_for_tm_t ig_tm_md, 
            in ingress_intrinsic_metadata_t ig_intr_md, 
            inout ingress_intrinsic_metadata_for_deparser_t ig_dprsr_md) {


    DirectCounter<bit<32>>(CounterType_t.PACKETS_AND_BYTES) debug_counter;

    // IAT monitoring
    Register<bit<16>, PortId_t>(256, 0) pkt_count;
    Register<bit<32>, PortId_t>(256, 0) lower_last_ts;
    Register<bit<16>, PortId_t>(256, 0) higher_last_ts;
    Register<bit<1>, PortId_t>(256, 0) hyperperiod_done;

    Register<bit<32>, PortId_t>(256, 0) period_count;

    StreamFilter() streamFilter_c;
    StreamGate() streamGate_c;
    FlowMeter() flowMeter_c;


    // Read the previous value from this register. Set it to 1 afterwards.
    RegisterAction<bit<1>, PortId_t, bit<1>>(hyperperiod_done) handle_hyperperiod_done = {
            void apply(inout bit<1> value, out bit<1> read_value) {
                read_value = value;
                value = 1;
            }
    };

    // Write lower 32 bit of timestamp 
    RegisterAction<bit<32>, PortId_t, void>(lower_last_ts) set_lower_last_ts = {
            void apply(inout bit<32> value) {
                value = ig_intr_md.ingress_mac_tstamp[31:0];
            }
    };

    // Read lower 32 bit of timestamp
    RegisterAction<bit<32>, PortId_t, bit<32>>(lower_last_ts) get_lower_last_ts = {
            void apply(inout bit<32> value, out bit<32> read_value) {
                read_value = value;
                value = value;
            }
    };

    // Write higher 16 bit of timestamp 
    RegisterAction<bit<16>, PortId_t, void>(higher_last_ts) set_higher_last_ts = {
            void apply(inout bit<16> value) {
                value = ig_intr_md.ingress_mac_tstamp[47:32];
            }
    };

    // Read higher 16 bit of timestamp 
    RegisterAction<bit<16>, PortId_t, bit<16>>(higher_last_ts) get_higher_last_ts = {
            void apply(inout bit<16> value, out bit<16> read_value) {
                read_value = value;
                value = value;
            }
    };

    // Handle pkt count
    RegisterAction<bit<16>, PortId_t, bit<16>>(pkt_count) handle_pkt_count = {
            void apply(inout bit<16> value, out bit<16> read_value) {
                // Increment
                bit<16> count = value + 1;
                read_value = value;
                if (count == ig_md.hyperperiod.pkt_count_hyperperiod){
                    // Reset value
                    value = 0;
                } else {
                    value = count;
                }
                read_value = value;
            }
    };

    // Increment period
    RegisterAction<bit<32>, PortId_t, bit<32>>(period_count) increment_period_count = {
        void apply(inout bit<32> value) {
            value = value + 1;
        }
    };

    RegisterAction<bit<32>, PortId_t, bit<32>>(period_count) get_period_count = {
        void apply(inout bit<32> value, out bit<32> read_value) {
            read_value = value;
        }
    };

    action set_pkt_count(bit<16> pkt_count_hyperperiod){
        ig_md.hyperperiod.pkt_count_hyperperiod = pkt_count_hyperperiod;

        debug_counter.count();
    }

    action assign_app_id_port(PortId_t port){
        ig_md.hyperperiod.port = port;
    }

    table timed_pkt {
        key = {
            hdr.timer.pipe_id : exact;
            hdr.timer.app_id  : exact;
            hdr.timer.batch_id : exact;
            hdr.timer.packet_id : exact;
            ig_intr_md.ingress_port : exact;
        }
        actions = {
            set_pkt_count;
        }
        counters = debug_counter; 
        size = 16; 
    }

    action set_recirculation_port(PortId_t recirc_port){
        ig_tm_md.ucast_egress_port = recirc_port;
    }

    table mapping_ingress_recirculation_port {
        key = {
            ig_intr_md.ingress_port: exact;
        }
        actions = {
            set_recirculation_port;
        }
        size = 16;
    }
    
    
    action calc_diff_ts(){
        /*
        Calculates the relative position in the hyperperiod by subtracting ingress ts from hyperperiod ts
        */
        hdr.bridge.diff_ts = hdr.bridge.ingress_timestamp - hdr.bridge.hyperperiod_ts;
    }


    /*
    This table maps the app_id of a schedule to an input port.
    This allows us to have 8 different hyperperiod schedules per switch 
    (one per port).
    */
    table app_id_port {
        key = {
            hdr.timer.app_id: exact;
        }
        actions = {
            assign_app_id_port;
        }
        size = 8;
    }

    apply {
        /* 
        Depending on the ingress port, the hyperperiod register will be updated
        with the most recent ingress timestamp (ingress port == pkt gen port, generated packet)
        or the latest value will be read into ig_md.hyperperiod.hyperperiod_ts (PSFP eligible packet).
        */
        if(ig_intr_md.ingress_port == PACKET_GEN_PORT_PIPE0 || ig_intr_md.ingress_port == PACKET_GEN_PORT_PIPE1){
            // Generated packet
            if (timed_pkt.apply().hit){
                if (app_id_port.apply().hit){;
                    // Increments or resets the packet count register
                    ig_md.hyperperiod.pkt_count_register = handle_pkt_count.execute(ig_md.hyperperiod.port);

                    if (ig_md.hyperperiod.pkt_count_register == 0){
                        // Write new hyperperiod timestamp and reset pkt_count
                        set_lower_last_ts.execute(ig_md.hyperperiod.port);
                        set_higher_last_ts.execute(ig_md.hyperperiod.port);

                        bit<1> is_hyperperiod_done = handle_hyperperiod_done.execute(ig_md.hyperperiod.port);

                        if (is_hyperperiod_done == 0){
                            // Only send a digest for the first hyperperiod done.
                            // Otherwise we would flood the control plane with digests
                            ig_dprsr_md.digest_type = 6;
                        }

                        increment_period_count.execute(ig_md.hyperperiod.port);
                    } 
                }
                // Send a digest for debugging
                //ig_dprsr_md.digest_type = 4;

                // Drop Packet, its work is done here.
                ig_dprsr_md.drop_ctl = 0x1;
            }
        } else if (!hdr.recirc.isValid()){
            // ! BEFORE recirculation

            // Read the last timestamp from 48-bit register and write it into bridge header
            hdr.bridge.hyperperiod_ts[31:0] = get_lower_last_ts.execute(ig_intr_md.ingress_port);
            hdr.bridge.hyperperiod_ts[47:32] = get_higher_last_ts.execute(ig_intr_md.ingress_port);

            // Retrieve period count
            hdr.bridge.period_count = get_period_count.execute(ig_intr_md.ingress_port);

            /*
            Ingress to egress bridge header
            */
            hdr.bridge.setValid();

            hdr.bridge.ingress_port = (bit<16>) ig_intr_md.ingress_port;

            // Retrieve hyperperiod duration needed for underflow calculation
            hdr.bridge.ingress_timestamp = (bit<64>)ig_intr_md.ingress_mac_tstamp;

            // Calculate relative position
            calc_diff_ts(); 
                            
            // Recirculate
            mapping_ingress_recirculation_port.apply();

        } else {
            // ! AFTER recirculation
            ig_dprsr_md.drop_ctl = 0x0;

            // Do PSFP
            streamFilter_c.apply(hdr, ig_md, ig_tm_md, ig_intr_md, ig_dprsr_md);
            streamGate_c.apply(hdr, ig_md, ig_tm_md, ig_intr_md, ig_dprsr_md);
            flowMeter_c.apply(hdr, ig_md, ig_tm_md, ig_intr_md, ig_dprsr_md);

            // Dont send out the bridge and recirculation header in this case
            hdr.recirc.setInvalid();
            hdr.bridge.setInvalid();
        }     
    }
}