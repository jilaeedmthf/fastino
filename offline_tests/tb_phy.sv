`timescale 1ns/1ps
// Actual production PHY, including its clear/status wiring and native reset
// synchronizers. Only PLL outputs and decoded input frames are controlled here.
// These ideal clocks/LOCK injections do not model analog PLL acquisition.
module tb_phy;
    reg word_clk=0, spi_clk=0, serial_clk=0;
    reg word_running=1, spi_running=1, word_lock=0, spi_lock=0;
    reg frame_valid=0;
    reg [567:0] frame_body=0;
    reg [3:0] cfg_value=0;
    wire [223:0] status;
    wire clr_n;
    wire [31:0] sclk,nss,sdi,ldacn;
    wire [15:0] code[32];
    actual_phy dut(
`include "phy_connections.vh"
    );
    always #14 if(word_running) word_clk=~word_clk;
    always #10.5 if(spi_running) spi_clk=~spi_clk;
    always #2 serial_clk=~serial_clk;
    wire effective_spi_lock=spi_lock & dut.SB_PLL40_CORE.RESETB;
    initial begin
        force dut.SB_PLL40_2F_CORE.PLLOUTGLOBALA=word_clk;
        force dut.SB_PLL40_2F_CORE.PLLOUTGLOBALB=serial_clk;
        force dut.SB_PLL40_2F_CORE.LOCK=word_lock;
        force dut.SB_PLL40_CORE.PLLOUTGLOBAL=spi_clk;
        force dut.SB_PLL40_CORE.LOCK=effective_spi_lock;
        force dut.stb=frame_valid;
        force dut.body=frame_body;
    end
    genvar g;
    generate for(g=0;g<32;g=g+1) begin: dacs
        ad5542a_model #(.CHANNEL(g)) model(.sclk(sclk[g]),.nss(nss[g]),
            .sdi(sdi[g]),.ldacn(ldacn[g]),.clr_n(clr_n),.dac_code(code[g]),
            .input_word(),.serial_word(),.bits_seen(),.zero_transfers());
        always @(code[g]) begin
            #0.01;
            if(clr_n===0 && code[g]!==16'h8000)
                $fatal(1,"PHY nonzero while clear ch%0d",g);
        end
    end endgenerate
    task word_ticks(input integer count);
        repeat(count) @(posedge word_clk); #1;
    endtask
    task send_cfg(input [3:0] value);
        @(negedge word_clk); #1;
        cfg_value=value; frame_body=0; frame_body[3:0]=value; frame_valid=1;
        @(negedge word_clk); #1; frame_valid=0;
        word_ticks(4);
    endtask
    task assert_status(input bit ready,input bit history);
        if(status[7:0]!==8'hfa || status[19:17]!==3'd1)
            $fatal(1,"PHY identity");
        if(status[83:72]!==12'ha51 || status[71]!==history || status[70]!==ready ||
           status[20]!==history || status[61]!==ready)
            $fatal(1,"PHY status ready/history got%h expected %b%b",status[83:70],history,ready);
    endtask
    task recovered;
        wait(status[61]===1); word_ticks(3);
        if(clr_n!==1 || nss!==32'hffffffff) $fatal(1,"PHY ready before startup complete");
        for(integer j=0;j<32;j=j+1)
            if(code[j]!==16'h8000) $fatal(1,"PHY startup zero ch%0d",j);
    endtask
    task acknowledge;
        send_cfg(0); send_cfg(8); assert_status(1,0); send_cfg(0);
    endtask
    integer address, offset;
    initial begin
        // Explicit zero-RAM model; run script separately verifies packed ASC
        // when --ram-image is provided. Unknown-RAM cold-idle tests are separate.
        for(address=0;address<16;address=address+1) begin
            dut.mem[address]=0; dut.mem_1[address]=0;
        end
        #100;
        if(clr_n!==0) $fatal(1,"PHY clear not asserted during reset");
        word_lock=1; spi_lock=1;
        recovered; assert_status(1,1); acknowledge;
        $display("PASS actual PHY identity, startup zero and acknowledged history");

        // Fault while acknowledgement is held high must survive recovery.
        send_cfg(8); assert_status(1,0);
        @(negedge spi_clk); #1; spi_lock=0;
        #2; if(clr_n!==0) $fatal(1,"PHY clear not asserted during reset");
        word_ticks(5); assert_status(0,1);
        spi_lock=1; recovered; assert_status(1,1);
        word_ticks(12); assert_status(1,1);
        acknowledge;
        $display("PASS held clr_err cannot erase a new fault on recovery");

        // A 2 ns digital LOCK pulse is captured by the existing async reset
        // primitive and stretched; this is not an analog minimum-pulse claim.
        @(negedge spi_clk); #1; spi_lock=0; #2; spi_lock=1;
        word_ticks(4); assert_status(0,1);
        recovered; assert_status(1,1); acknowledge;
        $display("PASS short injected LOCK pulse is retained");

        // The cfg register accepts clr_err one edge before its acknowledgement
        // is consumed. Inject reset immediately before/on/after that edge.
        for(offset=-1;offset<=1;offset=offset+1) begin
            send_cfg(0);
            @(negedge word_clk); #1;
            frame_body=0; frame_body[3]=1; frame_valid=1;
            @(negedge word_clk); #1; frame_valid=0;
            #(13+offset); spi_lock=0; #2; spi_lock=1;
            word_ticks(4); assert_status(0,1);
            recovered; assert_status(1,1);
            acknowledge;
        end
        $display("PASS reset wins acknowledgement-edge races");

        // Reset remains detectable when SPI cannot clock its startup sequence.
        @(negedge spi_clk); #1; spi_running=0; spi_lock=0;
        #2; if(clr_n!==0) $fatal(1,"PHY stopped-clock reset clear");
        spi_lock=1; word_ticks(8); assert_status(0,1);
        send_cfg(8); assert_status(0,1); // reject, never queue this ack
        spi_running=1; recovered; assert_status(1,1);
        acknowledge;
        $display("PASS stopped SPI and early rejected acknowledgement");

        // Stop the observation clock too: the native async event latch must
        // retain history until the sys-domain synchronizers can run again.
        @(negedge word_clk); #1; word_running=0;
        @(negedge spi_clk); #1; spi_running=0;
        spi_lock=0; #2; spi_lock=1; #200;
        if(clr_n!==0) $fatal(1,"PHY all clocks stopped clear");
        spi_running=1; #1000;
        word_running=1; word_ticks(8); assert_status(1,1); acknowledge;
        $display("PASS event survives stopped SPI and word clocks");

        // A deliberate configured PLL reset is also a reset-history event.
        send_cfg(1); assert_status(0,1);
        send_cfg(9); assert_status(0,1);
        send_cfg(8); recovered; assert_status(1,1);
        acknowledge;
        $display("PASS deliberate SPI reset is reported without auto-clear");

        // Loss of the word PLL resets sys/cfg and also resets the SPI PLL.
        // Its history survives both clock-domain resets and subsequent recovery.
        word_lock=0; #2;
        if(clr_n!==0) $fatal(1,"PHY word reset clear");
        word_ticks(4); word_lock=1;
        recovered; assert_status(1,1); acknowledge;
        $display("PASS word PLL loss and sys reset preserve reset history");

        // Kasli may retain a high clear header across a Fastino word reset.
        // The reset default of cfg=0 must not count as a received low command,
        // even if the old high packet arrives long after serializer recovery.
        send_cfg(8); assert_status(1,0);
        word_lock=0; word_ticks(4); word_lock=1;
        recovered; assert_status(1,1);
        send_cfg(8); assert_status(1,1);
        send_cfg(8); assert_status(1,1);
        acknowledge;
        $display("PASS held-high controller header across sys reset cannot acknowledge");

        // Stop sys after it accepts a high command, before it consumes the
        // acknowledgement. A later SPI reset/recovery must invalidate that
        // pre-fault request even while the word clock cannot run.
        send_cfg(0);
        @(negedge word_clk); #1;
        frame_body=0; frame_body[3]=1; frame_valid=1;
        @(negedge word_clk); #1; frame_valid=0; word_running=0;
        spi_lock=0; #2; spi_lock=1; #1000;
        word_running=1; word_ticks(8); assert_status(1,1);
        acknowledge;
        $display("PASS pre-fault pending acknowledgement invalidated with sys stopped");

        // Software DAC clear does not imply SPI unavailability or a PLL fault.
        send_cfg(4); assert_status(1,0);
        if(clr_n!==0) $fatal(1,"PHY software clear wiring");
        send_cfg(0); assert_status(1,0);
        if(clr_n!==1) $fatal(1,"PHY software clear release wiring");
        $display("PASS serializer readiness remains distinct from software CLR");
        $display("ALL ACTUAL PHY TESTS PASSED");
        $finish;
    end
    initial begin #100000; $fatal(1,"PHY timeout"); end
endmodule
