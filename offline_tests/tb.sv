`timescale 1ns/1ps
module tb;
    string vcd_path;
    initial if ($value$plusargs("vcd=%s", vcd_path)) begin
        $dumpfile(vcd_path);
        $dumpvars(0,spi_clk,spi_rst,clr_n,startup_clear,sclk,nss,sdi);
        #2500; $dumpoff;
    end
    reg spi_clk=0, running=0, spi_rst=1, soft_clear=0, stb=0;
    reg [543:0] data=0;
    wire clr_n,startup_clear,busy;
    wire [31:0] sclk,nss,sdi,ldacn;
    wire old_clr,old_startup,old_busy;
    wire [31:0] old_sclk,old_nss,old_sdi,old_ldac;
    reg compare_normal=0;
    candidate dut(.*);
    baseline old(.spi_clk(spi_clk),.spi_rst(spi_rst),.soft_clear(soft_clear),
        .data(data),.stb(stb),.clr_n(old_clr),.startup_clear(old_startup),
        .busy(old_busy),.sclk(old_sclk),.nss(old_nss),.sdi(old_sdi),.ldacn(old_ldac));
    always #10.5 if(running) spi_clk=~spi_clk;
    wire [15:0] codes[32],inputs[32],serials[32];
    wire [31:0] counts[32],zeros[32];
    genvar g;
    generate for(g=0;g<32;g=g+1) begin: channels
        ad5542a_model #(.CHANNEL(g)) dac(.sclk(sclk[g]),.nss(nss[g]),.sdi(sdi[g]),
            .ldacn(ldacn[g]),.clr_n(clr_n),.dac_code(codes[g]),.input_word(inputs[g]),
            .serial_word(serials[g]),.bits_seen(counts[g]),.zero_transfers(zeros[g]));
        integer zeros_at_reset=0;
        always @(posedge spi_rst) zeros_at_reset=zeros[g];
        always @(negedge startup_clear) begin
            #0.01;
            if (!spi_rst) begin
                if(nss[g]!==1 || inputs[g]!==16'h8000 || counts[g]!=16)
                    $fatal(1,"startup release lacks full zero ch%0d",g);
                if(zeros[g]<=zeros_at_reset) $fatal(1,"no new zero transfer ch%0d",g);
                if($realtime-dac.cs_rose<41.99) $fatal(1,"CS release margin ch%0d",g);
            end
        end
        always @(codes[g]) begin
            #0.01;
            if(clr_n===0 && codes[g]!==16'h8000)
                $fatal(1,"partial/nonzero escaped CLR ch%0d",g);
        end
    end endgenerate
    always @(posedge spi_clk or negedge spi_clk) begin
        #0.01;
        if(compare_normal && {sclk,nss,sdi,ldacn,busy} !==
                             {old_sclk,old_nss,old_sdi,old_ldac,old_busy})
            $fatal(1,"normal serializer differs from v0.2 at %0t",$time);
    end

    // Separate real two-interpolator pipeline, with the same input register
    // boundary as Fastino. Link/PLL behavior is represented by reset and clocks.
    reg ir=1, ifstb=0, iftyp=0, isoft=0;
    reg [31:0] ifen=0;
    reg [511:0] ifdata=0;
    wire iclr,istart,ibusy,pstb;
    wire [31:0] isclk,inss,isdi,ildac,pen;
    wire [15:0] icodes[32];
`ifdef LEGACY_INTERPOLATOR
    legacy_integrated
`else
    integrated
`endif
    ip(.spi_clk(spi_clk),.spi_rst(ir),.soft_clear(isoft),
        .clr_n(iclr),.startup_clear(istart),.busy(ibusy),.sclk(isclk),.nss(inss),
        .sdi(isdi),.ldacn(ildac),.frame_stb(ifstb),.frame_typ(iftyp),
        .frame_enable(ifen),.frame_data(ifdata),.producer_stb(pstb),.producer_enable(pen));
    integer ram_address;
    initial if($test$plusargs("fpga_ram_init_zero")) begin
        // Actual candidate ASC contains32 all-zero 4kbit RAM init blocks.
        // Unmapped Migen RTL leaves these memories X. Match the built image
        // only in this explicitly labeled variant; serial registers stay random/X.
        for(ram_address=0;ram_address<16;ram_address=ram_address+1) begin
            ip.mem[ram_address]=0;
            ip.mem_1[ram_address]=0;
        end
    end
    generate for(g=0;g<32;g=g+1) begin: integrated_channels
        ad5542a_model #(.CHANNEL(g+32)) dac(.sclk(isclk[g]),.nss(inss[g]),.sdi(isdi[g]),
            .ldacn(ildac[g]),.clr_n(iclr),.dac_code(icodes[g]),.input_word(),
            .serial_word(),.bits_seen(),.zero_transfers());
    end endgenerate
    reg expect_idle_mask=0;
    always @(posedge spi_clk) if(expect_idle_mask && pstb && pen!==0)
        $fatal(1,"stale interpolator mask after reset: %h",pen);

    task tick(input integer n);
        repeat(n) @(posedge spi_clk);
        #1;
    endtask
    task low_edge;
        @(negedge spi_clk); #1;
    endtask
    task zero_check;
        integer j;
        if(clr_n!==(soft_clear ? 1'b0 : 1'b1) || startup_clear!==0 || nss!==32'hffffffff)
            $fatal(1,"not ready");
        for(j=0;j<32;j=j+1)
            if(codes[j]!==16'h8000 || inputs[j]!==16'h8000) $fatal(1,"zero ch%0d",j);
    endtask
    task restart;
        compare_normal=0; stb=0;
        low_edge; spi_rst=1;
        #1; if(clr_n!==0) $fatal(1,"reset must assert clear immediately");
        tick(3); low_edge; spi_rst=0;
        wait(startup_clear===0); #1; zero_check;
    endtask
    function [15:0] word(input integer ch,input integer seq);
        word=16'h1000+ch*17+seq*101;
    endfunction
    reg [15:0] expected[32];
    task transfer(input [31:0] mask,input integer seq);
        integer j;
        low_edge;
        data[31:0]=mask;
        for(j=0;j<32;j=j+1) data[32+16*j+:16]=word(j,seq);
        stb=1;
        tick(1); low_edge; stb=0;
        tick(17);
        for(j=0;j<32;j=j+1) begin
            if(mask[j]) expected[j]=word(j,seq);
            if(codes[j]!==expected[j]) $fatal(1,"normal data ch%0d seq%0d got%h expected%h",j,seq,codes[j],expected[j]);
        end
    endtask
    task iframe(input bit typ,input [31:0] mask,input [15:0] value);
        integer j;
        low_edge; iftyp=typ; ifen=mask;
        for(j=0;j<32;j=j+1) ifdata[16*j+:16]=value;
        ifstb=1; tick(1); low_edge; ifstb=0; tick(18);
    endtask

    integer j,k,phase;
    initial begin
        // No SPI clock: only CLR is guaranteed, not registered CS/SCLK pins.
        #500;
        if(clr_n!==0 || startup_clear!==1) $fatal(1,"no-clock startup released");
        running=1; tick(3); low_edge; spi_rst=0;
        wait(startup_clear===0); #1; zero_check;
        $display("PASS no-clock and late-clock startup all32");

        for(phase=0;phase<24;phase=phase+1) begin
            low_edge; spi_rst=1; tick(3); low_edge; spi_rst=0;
            if(phase>0) tick(phase);
            restart;
        end
        $display("PASS reset at every startup phase");

        for(phase=0;phase<21;phase=phase+1) begin
            low_edge; spi_rst=1; tick(3); low_edge; spi_rst=0;
            if(phase>0) tick(phase);
            low_edge; running=0;
            #420;
            if(clr_n!==0 || startup_clear!==1) $fatal(1,"stopped startup released phase%0d",phase);
            running=1; wait(startup_clear===0); #1; zero_check;
        end
        $display("PASS stopped/resumed startup clock");

        // SPI reset must pull clear low even with a stopped clock and a previous
        // completed startup. Clock resumption must execute a fresh full zero.
        low_edge; running=0; spi_rst=1; #400;
        if(clr_n!==0) $fatal(1,"stopped-clock reset did not assert clear");
        running=1; tick(3); low_edge; spi_rst=0;
        wait(startup_clear===0); #1; zero_check;
        $display("PASS asynchronous stopped-clock reset assertion");

        for(j=0;j<32;j=j+1) expected[j]=16'h8000;
        compare_normal=1;
        transfer(32'hffffffff,1);
        transfer(32'h00000000,2);
        transfer(32'ha5a55a5a,3);
        for(k=0;k<32;k=k+1) transfer(32'b1<<k,k+4);
        compare_normal=0;
        $display("PASS all-channel masks/data and v0.2 pin timing/throughput");

        soft_clear=1; #100;
        for(j=0;j<32;j=j+1) if(codes[j]!==16'h8000) $fatal(1,"software clear assert");
        soft_clear=0; #100;
        for(j=0;j<32;j=j+1) if(codes[j]!==16'h8000) $fatal(1,"software clear release changed DAC");
        restart;
        soft_clear=1; restart;
        if(clr_n!==0) $fatal(1,"software clear precedence");
        soft_clear=0; #1; zero_check;
        $display("PASS software clear after nonzero and during startup");

        // Keep data queued across handover: startup owns the bus first, then
        // the first ordinary strobe after startup is serviced unchanged.
        low_edge; spi_rst=1; tick(3); low_edge; spi_rst=0;
        data[31:0]=32'hffffffff;
        for(j=0;j<32;j=j+1) data[32+16*j+:16]=word(j,71);
        stb=1; wait(startup_clear===0); #1; zero_check;
        tick(1); low_edge; stb=0; tick(18);
        for(j=0;j<32;j=j+1) if(codes[j]!==word(j,71)) $fatal(1,"handover data ch%0d",j);
        $display("PASS pending traffic at handover");

        // Real interpolators: initial zero-mask idle frames, with no host CIC
        // or DAC initialization, must not defeat serializer startup zero.
        low_edge; ir=0;
        wait(istart===0); #1;
        expect_idle_mask=1;
        for(k=0;k<12;k=k+1) iframe(0,0,16'hffff);
        tick(30);
        for(j=0;j<32;j=j+1) if(icodes[j]!==16'h8000) $fatal(1,"cold idle ch%0d",j);
        expect_idle_mask=0;
        $display("PASS real interpolator cold idle zero masks");
        if(!$test$plusargs("fpga_ram_init_zero")) begin
            $display("PASS undefined-RAM cold idle; active-output regression requires image-matched RAM variant");
            $finish;
        end

        for(phase=0;phase<19;phase=phase+1) begin
            // Establish unity CIC, produce nonzero output, reset mid pipeline.
            iframe(1,32'hffffffff,0);
            for(k=0;k<12;k=k+1) iframe(0,32'hffffffff,16'hffff);
            for(j=0;j<32;j=j+1) if(icodes[j]!==16'hffff)
                $fatal(1,"warm-reset precondition not active ch%0d phase%0d got%h",j,phase,icodes[j]);
            low_edge; ifstb=1; tick(1); low_edge; ifstb=0;
            if(phase>0) tick(phase);
            low_edge; ir=1; tick(3); low_edge; ir=0;
            // No frames through startup, then deliberately delayed idle input.
            tick(100);
            expect_idle_mask=1;
            for(k=0;k<6;k=k+1) iframe(0,0,16'hffff);
            tick(30);
            for(j=0;j<32;j=j+1) if(icodes[j]!==16'h8000) $fatal(1,"warm idle ch%0d phase%0d",j,phase);
            expect_idle_mask=0;
        end
        $display("PASS real interpolator warm reset all19 phases delayed idle masks");
        $display("ALL PIN/RTL TESTS PASSED");
        $finish;
    end
    initial begin #5000000; $fatal(1,"timeout"); end
endmodule
