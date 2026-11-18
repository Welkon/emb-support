`timescale 1ns/1ps
// Minimal I2C master stimulus: writes 0x00 0x53 to 0x50, then reads one byte.
module i2c_tb;
  reg scl = 1'b1;
  reg sda = 1'b1;
  reg sda_oe = 1'b1;      // 1 = master drives SDA
  wire sda_line = sda_oe ? sda : 1'bz;

  task half(input integer n); begin #(n); end endtask
  task bit_out(input b); begin
    scl = 0; half(2500); sda = b; half(2500); scl = 1; half(5000);
  end endtask
  task bit_in(output b); begin
    sda_oe = 0; scl = 0; half(5000); b = sda_line; scl = 1; half(5000); sda_oe = 1;
  end endtask
  task start; begin sda = 0; half(5000); scl = 0; half(5000); end endtask
  task stop; begin sda = 0; scl = 0; half(5000); scl = 1; half(5000); sda = 1; half(5000); end endtask

  integer i; reg [7:0] data; reg ack;
  initial begin
    $dumpfile("/tmp/iv/i2c.vcd"); $dumpvars(0, i2c_tb);
    #100000;
    start; data = 8'hA0; for (i = 7; i >= 0; i = i - 1) bit_out(data[i]); bit_in(ack);
    data = 8'h00; for (i = 7; i >= 0; i = i - 1) bit_out(data[i]); bit_in(ack);
    data = 8'h53; for (i = 7; i >= 0; i = i - 1) bit_out(data[i]); bit_in(ack);
    stop; #50000;
    start; data = 8'hA1; for (i = 7; i >= 0; i = i - 1) bit_out(data[i]); bit_in(ack);
    bit_in(data); bit_out(1'b1);   // read 0x33 semantics not important; NACK ends it
    stop; #50000; $finish;
  end
endmodule
