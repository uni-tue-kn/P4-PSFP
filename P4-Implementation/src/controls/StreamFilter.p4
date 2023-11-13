control StreamFilter(inout header_t hdr, 
            inout ingress_metadata_t ig_md, 
            inout ingress_intrinsic_metadata_for_tm_t ig_tm_md, 
            in ingress_intrinsic_metadata_t ig_intr_md, 
            inout ingress_intrinsic_metadata_for_deparser_t ig_dprsr_md) {


    DirectCounter<bit<32>>(CounterType_t.PACKETS_AND_BYTES) stream_id_counter;
    DirectCounter<bit<32>>(CounterType_t.PACKETS_AND_BYTES) stream_id_overwrite_counter;
    DirectCounter<bit<32>>(CounterType_t.PACKETS_AND_BYTES) stream_filter_counter;
    // Counts frames that passed SDU filter
    DirectCounter<bit<32>>(CounterType_t.PACKETS_AND_BYTES) max_sdu_filter_counter;
    // Counts frames that did not pass SDU filter
    Counter<bit<32>, bit<16>>(32, CounterType_t.PACKETS) missed_max_sdu_filter_counter;
    Counter<bit<32>, bit<16>>(512, CounterType_t.PACKETS_AND_BYTES) overall_counter;
    
    Register<bit<1>, void>(__STREAM_ID_SIZE__, 0) reg_filter_blocked;
    RegisterAction<bit<1>, bit<16>, void>(reg_filter_blocked) block_filter = {
        void apply(inout bit<1> value){
            value = 1;
        }
    };

    RegisterAction<bit<1>, bit<16>, bit<1>>(reg_filter_blocked) get_filter_state = {
        void apply(inout bit<1> value, out bit<1> read_value){
            read_value = value;
        }
    };


    action none() {
        max_sdu_filter_counter.count();
    }

    action overwrite_stream_active(mac_addr_t eth_dst_addr, bit<12> vid, bit<3> pcp){
        // Used for active stream identification function 
        hdr.ethernet.dst_addr = eth_dst_addr;
        hdr.eth_802_1q.vid = vid;
        hdr.eth_802_1q.pcp = pcp;

        stream_id_overwrite_counter.count();
    }

    action assign_stream_handle(bit<16> stream_handle, bool active, 
                                bool stream_blocked_due_to_oversize_frame_enable){

        // Assign the stream_handle to identifiy this stream
        // Sets the 'active' flag which is used to determine if fields will be overwritten
        ig_md.stream_filter.stream_handle = stream_handle;
        ig_md.stream_filter.active_stream_identification = active;

        ig_md.stream_filter.stream_blocked_due_to_oversize_frame_enable = stream_blocked_due_to_oversize_frame_enable;


        stream_id_counter.count();
    }

    action assign_gate_and_meter(bit<12> stream_gate_id, 
                                bit<16> flow_meter_instance_id,
                                bool gate_closed_due_to_invalid_rx_enable,
                                bool gate_closed_due_to_octets_exceeded_enable) {

        ig_md.stream_filter.stream_gate_id = stream_gate_id;
        ig_md.stream_filter.flow_meter_instance_id = flow_meter_instance_id;

        ig_md.stream_gate.gate_closed_due_to_invalid_rx_enable = gate_closed_due_to_invalid_rx_enable;
        ig_md.stream_gate.gate_closed_due_to_octets_exceeded_enable = gate_closed_due_to_octets_exceeded_enable;

        stream_filter_counter.count();
    }

    /*
    Table to do stream identification and assign the stream_handle
    */
    #if __STREAM_ID__ == 1
        // Null stream ID only + active ID
        table stream_id {
        key = {
            hdr.ethernet.dst_addr: exact;     // Null stream + active identification
            hdr.eth_802_1q.vid: exact;
        }
        actions = {
            assign_stream_handle;
        }
        size = __STREAM_ID_SIZE__;
        counters = stream_id_counter;
    }
    #elif __STREAM_ID__ == 2 
        table stream_id {
            key = {
                hdr.ethernet.dst_addr: ternary;     // Null stream + active identification
                hdr.ethernet.src_addr: exact;     // Null stream + active identification
                hdr.eth_802_1q.vid: exact;
            }
            actions = {
                assign_stream_handle;
            }
            size = __STREAM_ID_SIZE__;
            counters = stream_id_counter;
        }
    #elif __STREAM_ID__ == 3
        table stream_id {
        key = {
            hdr.ethernet.dst_addr: ternary;     // Null stream + active identification
            hdr.eth_802_1q.vid: exact;

            hdr.ethernet.src_addr: ternary;     // Eth Src Identification

            hdr.ipv4.srcAddr: ternary;          // IP stream identification
            hdr.ipv4.dstAddr: ternary;
            hdr.ipv4.diffserv: ternary;
            hdr.ipv4.protocol: ternary;
            hdr.transport.srcPort: ternary;    
            hdr.transport.dstPort: ternary;
        }
        actions = {
            assign_stream_handle;
        }
        size = __STREAM_ID_SIZE__;
        counters = stream_id_counter;
    }
    #else
        table stream_id {
        key = {
            hdr.ethernet.dst_addr: exact;     // Null stream + active identification
            hdr.eth_802_1q.vid: exact;

            hdr.ipv4.srcAddr: exact;          // IP stream identification
            hdr.ipv4.dstAddr: exact;
            hdr.ipv4.diffserv: exact;
            hdr.ipv4.protocol: exact;
            hdr.transport.srcPort: exact;    
            hdr.transport.dstPort: exact;
        }
        actions = {
            assign_stream_handle;
        }
        size = __STREAM_ID_SIZE__;
        counters = stream_id_counter;
    }
    #endif    

    /*
    Table to do active stream identification and overwrite some fields
    */
    table stream_id_active {
        key = {
            ig_md.stream_filter.stream_handle: exact;
        }
        actions = {
            overwrite_stream_active;
        }
        size = 256;
        counters = stream_id_overwrite_counter;
    }

    /*
    Table to map from stream_handle to stream gate and flow meter
    */
    table stream_filter_instance {
        key = {
            ig_md.stream_filter.stream_handle: exact;
        }
        actions = {
            assign_gate_and_meter;
        }
        counters = stream_filter_counter;
        size = __STREAM_ID_SIZE__;
    }

    /*
    Keep SDU Filter table as separate instance, else we can not distinguish 
    if the packet does not have a stream_handle or gets rejected because of max SDU size
    */
    table max_sdu_filter {
        key = {
            ig_md.stream_filter.stream_handle: exact;
            hdr.eth_802_1q.pcp: ternary;
            hdr.recirc.pkt_len: range;
        }
        actions = {
            none;
        }
        counters = max_sdu_filter_counter;
        default_action = none;
        size = 512;
    }

    apply {
        // 1. First match on stream identification --> assign stream_handle
        if (stream_id.apply().hit){

            if (max_sdu_filter.apply().miss){
                if (ig_md.stream_filter.stream_blocked_due_to_oversize_frame_enable){
                    // Permanently block out this stream from communicating if enabled!
                    block_filter.execute(ig_md.stream_filter.stream_handle);
                }
                
                // Drop anyway because SDU exceeded
                ig_dprsr_md.drop_ctl = 0x1;
                missed_max_sdu_filter_counter.count(ig_md.stream_filter.stream_handle);
            } else {
                ig_md.stream_filter.stream_blocked_due_to_oversize_frame = get_filter_state.execute(ig_md.stream_filter.stream_handle);

                // 2. Match on assigned stream_handle --> assign stream_gate
                if (stream_filter_instance.apply().hit){
                    // --> stream_handle mapping exists! Continue

                    overall_counter.count(ig_md.stream_filter.flow_meter_instance_id);

                    if (ig_md.stream_filter.stream_blocked_due_to_oversize_frame_enable && ig_md.stream_filter.stream_blocked_due_to_oversize_frame == 1){
                        // Stream is already permanently blocked
                        ig_dprsr_md.drop_ctl = 0x1;
                    } else if (ig_md.stream_filter.active_stream_identification){
                        // Control plane decided to do active ID, meaning some fields will be overwritten.
                        stream_id_active.apply();
                    }
                }
            }
        }
    }
}
