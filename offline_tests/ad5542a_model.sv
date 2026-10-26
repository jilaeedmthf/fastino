`timescale 1ns/1ps
// Functional AD5542A model: Rev C pp6,8,15,17. Analog rails, analog settling,
// and the interval before FPGA configuration are outside this model.
// https://www.analog.com/media/en/technical-documentation/data-sheets/AD5512A_5542A.pdf
module ad5542a_model #(parameter CHANNEL=0)(
    input sclk, nss, sdi, ldacn, clr_n,
    output reg [15:0] dac_code = 16'h8000,
    output reg [15:0] input_word,
    output reg [15:0] serial_word,
    output integer bits_seen = 0,
    output integer zero_transfers = 0
);
    realtime cs_fell=0, cs_rose=0, last_rise=0, last_fall=0, data_changed=0;
    realtime clear_fell=0;
    integer serial_seed;
    initial begin
        // POR initializes DAC register, but explicitly does not clear serial
        // register. Exercise unknown and seeded arbitrary power-up state.
        if (!$value$plusargs("seed=%d", serial_seed)) serial_seed=1;
        serial_seed=serial_seed+CHANNEL*731;
        serial_word=$random(serial_seed);
        if ($test$plusargs("unknown_serial")) serial_word=16'hxxxx;
        input_word=16'hxxxx;
    end
    always @(sdi) begin
        if(last_rise>0 && $realtime-last_rise<5.0) $fatal(1,"data hold ch%0d",CHANNEL);
        data_changed=$realtime;
    end
    always @(negedge nss) begin
        if (cs_rose>0 && $realtime-cs_rose<15.0) $fatal(1,"CS high time ch%0d",CHANNEL);
        cs_fell=$realtime;
        bits_seen=0;
    end
    always @(posedge sclk) if (nss===1'b0) begin
        if ($realtime-cs_fell<5.0) $fatal(1,"CS setup ch%0d",CHANNEL);
        if ($realtime-data_changed<10.0) $fatal(1,"data setup ch%0d",CHANNEL);
        if (last_rise>0 && $realtime-last_rise<20.0) $fatal(1,"SCLK period ch%0d",CHANNEL);
        if (last_fall>0 && $realtime-last_fall<10.0) $fatal(1,"SCLK low ch%0d",CHANNEL);
        serial_word={serial_word[14:0],sdi};
        bits_seen=bits_seen+1;
        last_rise=$realtime;
    end
    always @(negedge sclk) begin
        if (last_rise>0 && $realtime-last_rise<10.0) $fatal(1,"SCLK high ch%0d",CHANNEL);
        last_fall=$realtime;
    end
    always @(posedge nss) begin
        cs_rose=$realtime;
        // A partial write can expose undefined serial contents. Never paper
        // over it by accepting only transactions with 16 clocks.
        input_word=serial_word;
        if (bits_seen==16 && serial_word===16'h8000) zero_transfers=zero_transfers+1;
        if (clr_n===1'b1 && ldacn===1'b0) dac_code=input_word;
        if (bits_seen>0 && $realtime-last_rise<5.0) $fatal(1,"CS hold ch%0d",CHANNEL);
    end
    always @(negedge clr_n) begin
        dac_code=16'h8000;
        clear_fell=$realtime;
    end
    always @(posedge clr_n) if($realtime-clear_fell<15.0) $fatal(1,"CLR pulse width ch%0d",CHANNEL);
    always @(negedge ldacn) if (clr_n===1'b1) dac_code=input_word;
    // CLR release is not a CS/LDAC update event. The startup test separately
    // verifies that the full known input word is present before this release.
endmodule
