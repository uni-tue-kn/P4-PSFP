control FlowMeter(inout header_t hdr, 
            inout ingress_metadata_t ig_md, 
            inout ingress_intrinsic_metadata_for_tm_t ig_tm_md, 
            in ingress_intrinsic_metadata_t ig_intr_md, 
            inout ingress_intrinsic_metadata_for_deparser_t ig_dprsr_md) {

    DirectMeter(MeterType_t.BYTES) flow_meter;
    Counter<bit<32>, bit<16>>(512, CounterType_t.PACKETS_AND_BYTES) marked_red_counter;
    Counter<bit<32>, bit<16>>(512, CounterType_t.PACKETS_AND_BYTES) marked_yellow_counter;
    Counter<bit<32>, bit<16>>(512, CounterType_t.PACKETS_AND_BYTES) marked_green_counter;

    Register<bit<1>, void>(2048, 0) reg_meter_blocked;
    RegisterAction<bit<1>, bit<16>, void>(reg_meter_blocked) block_meter = {
        void apply(inout bit<1> value){
            value = 1;
        }
    };

    RegisterAction<bit<1>, bit<16>, bit<1>>(reg_meter_blocked) get_meter_state = {
        void apply(inout bit<1> value, out bit<1> read_value){
            read_value = value;
        }
    };

    action set_color_direct() {
        // Execute the Direct meter and write the color into metadata
        /*
        0: GREEN
        1: YELLOW
        2: YELLOW
        3: RED
        */
        // Color-Aware labeling: Pre-color is set accordingly (pre-color always green for color-blind mode)
        ig_tm_md.packet_color = (bit<2>)flow_meter.execute(ig_md.flow_meter.pre_color, -7);
    }

    action set_flow_meter_config(bool dropOnYellow, bool markAllFramesRedEnable, bool colorAware){
        ig_md.flow_meter.drop_on_yellow = dropOnYellow;
        ig_md.flow_meter.mark_all_frames_red_enable = markAllFramesRedEnable;
        ig_md.flow_meter.color_aware = colorAware;
    }

    table flow_meter_config {
        key = {
            ig_md.stream_filter.flow_meter_instance_id: exact; 
        }
        actions = {
            set_flow_meter_config;
        }
        size = __STREAM_ID_SIZE__;
    }

    table flow_meter_instance {
        key = {
            ig_md.stream_filter.flow_meter_instance_id: exact;
        }
        actions = {
            set_color_direct;
        }
        meters = flow_meter;
        size = __STREAM_ID_SIZE__;
    }

    apply {
        flow_meter_config.apply();

        // PRE-COLORING
        if (ig_md.flow_meter.color_aware && hdr.eth_802_1q.dei == 1){
            // We are in color-aware mode and the received pkt is labeled yellow.
            // --> Keep it yellow
            ig_md.flow_meter.pre_color = MeterColor_t.YELLOW;
        } else {
            // color-blind mode or no pre-color: Assume all pkts green
            ig_md.flow_meter.pre_color = MeterColor_t.GREEN;
        }

        if (ig_dprsr_md.drop_ctl == 0){
            // Only pay tokens for this packet if it is not supposed to be dropped anyway
            flow_meter_instance.apply();  
        }

        // Color evaluation
        if (ig_tm_md.packet_color == 1 || ig_tm_md.packet_color == 2){
            // Yellow colored
            ig_md.flow_meter.meter_blocked = get_meter_state.execute(ig_md.stream_filter.flow_meter_instance_id);
            if (ig_md.flow_meter.drop_on_yellow || ig_md.flow_meter.meter_blocked == 1){
                ig_dprsr_md.drop_ctl = 1;
                ig_tm_md.packet_color = 3;
                marked_red_counter.count(ig_md.stream_filter.flow_meter_instance_id);
            } else {
                // Set DropEligibileIndicator for yellow packet
                hdr.eth_802_1q.dei = 1;
                marked_yellow_counter.count(ig_md.stream_filter.flow_meter_instance_id);
            }
        } else if (ig_tm_md.packet_color == 3){
            // Red
            ig_dprsr_md.drop_ctl = 1;
            marked_red_counter.count(ig_md.stream_filter.flow_meter_instance_id);

            if (ig_md.flow_meter.mark_all_frames_red_enable){
                block_meter.execute(ig_md.stream_filter.flow_meter_instance_id);
                //if (ig_dprsr_md.digest_type == 0){
                    // Permanently mark all frames red for this flow meter
                    // Let control plane block it
                //    ig_md.block_reason = 3;
                //    ig_dprsr_md.digest_type = 1;
                //}
            }
        } else if (ig_tm_md.packet_color == 0 && ig_dprsr_md.drop_ctl == 0){
            ig_md.flow_meter.meter_blocked = get_meter_state.execute(ig_md.stream_filter.flow_meter_instance_id);
            if (ig_md.flow_meter.meter_blocked == 1){
                ig_dprsr_md.drop_ctl = 1;
                ig_tm_md.packet_color = 3;
                marked_red_counter.count(ig_md.stream_filter.flow_meter_instance_id);
            } else {
                hdr.eth_802_1q.dei = 0; // Mark this frame green again
                marked_green_counter.count(ig_md.stream_filter.flow_meter_instance_id);
            }
        }
    }
}
