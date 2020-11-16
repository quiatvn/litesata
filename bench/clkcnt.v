
module clkcnt
    (
     clkref,
     clkmon,
     rst,
     oval
     );

parameter     CLKCOUNT = 125000000;

input   clkref, clkmon, rst;

output reg [28:0] oval;

///////////////////////////////////////////////////////////////////////////////

reg [27:0] cnt1s;
wire       cnt1smax = cnt1s == (CLKCOUNT-1);
always @(posedge clkref)
    begin
    if(rst) cnt1s <= 28'b0;
    else cnt1s <= cnt1smax ? 28'b0 : (cnt1s + 1);
    end

///////////////////////////////////////////////////////////////////////////////
wire      detpulse = cnt1s[27:8] == 0;

reg [2:0] shift;
always @(posedge clkmon)
    begin
    if(rst) shift <= 3'b0;
    else shift <= {shift[1:0], detpulse};
    end

wire     edgedet;
assign   edgedet = shift == 3'b011;

reg [28:0] counter;
always @(posedge clkmon)
    begin
    if(rst) counter <= 29'b0;
    else if (edgedet) counter <= 29'b0;
    else counter <= counter + 1;
    end

always @(posedge clkmon)
    begin
    if(rst) oval <= 29'b0;
    else if (edgedet) oval <= counter;
    end


endmodule
