ila_0 ila_0(
    .clk     (sys_clk),
    .probe0  ({builder_litesataphy_gthrxinit_state, builder_litesataphy_state,
               //main_gthlitesataphy_rx_init_cdrhold1, main_gthlitesataphy_rx_init_cdrlock1,
               main_gthlitesataphy_rx_init_gtXxreset1, main_gthlitesataphy_rx_init_plllock1, main_gthlitesataphy_rx_init_Xxuserrdy1,
               main_gthlitesataphy_rx_init_gtXxpmareset1, main_gthlitesataphy_rx_init_Xxresetdone1, main_gthlitesataphy_rx_init_Xxsyncdone1}),
    .probe1   ({main_gthlitesataphy_txclk_period, main_gthlitesataphy_rxclk_period, main_ctrl_align_counter, main_ctrl_non_align_counter}),
    .probe2   ({main_gthlitesataphy_rx_cominit_stb, main_gthlitesataphy_tx_comwake_stb, main_gthlitesataphy_rx_comwake_stb,
                main_ctrl_sink_valid, main_ctrl_sink_payload_charisk, main_ctrl_sink_payload_data, 
                main_ctrl_source_payload_data, main_ctrl_source_payload_charisk, main_ctrl_source_payload_valid})
);





wire       RXDLYBYPASS, TXDLYBYPASS;
wire [2:0] RXOUTCLKSEL, TXOUTCLKSEL;
vio_0 vio_0(
    .clk       (sys_clk),
    .probe_out0(RXDLYBYPASS),
    .probe_out1(RXOUTCLKSEL),
    .probe_out2(TXDLYBYPASS),
    .probe_out3(TXOUTCLKSEL));

ila_0 ila_0(
    .clk     (sys_clk),
    .probe0  ({builder_litesataphy_gthrxinit_state, builder_litesataphy_state,
               //main_gthlitesataphy_rx_init_cdrhold1, main_gthlitesataphy_rx_init_cdrlock1,
               main_gthlitesataphy_rx_init_gtXxreset1, main_gthlitesataphy_rx_init_plllock1, main_gthlitesataphy_rx_init_Xxuserrdy1,
               main_gthlitesataphy_rx_init_gtXxpmareset1, main_gthlitesataphy_rx_init_Xxresetdone1, main_gthlitesataphy_rx_init_Xxsyncdone1}),
    .probe1   ({main_gthlitesataphy_txclk_period, main_gthlitesataphy_rxclk_period, main_ctrl_align_counter, main_ctrl_non_align_counter}),
    .probe2   (0)
);





ila_0 ila_0(
    .clk     (sys_clk),
    .probe0  ({builder_litesataphy_gtyrxinit_state, builder_litesataphy_state,
               main_ctrl_enable, main_ctrl_misalign,
               main_gtylitesataphy_rx_cominit_stb, main_gtylitesataphy_tx_comwake_stb, main_gtylitesataphy_rx_comwake_stb}),
    .probe1   ({main_gtylitesataphy_txclk_period, main_gtylitesataphy_rxclk_period, 
                main_ctrl_align_counter, main_ctrl_non_align_counter}),
    .probe2   ({
                main_ctrl_sink_valid, main_ctrl_sink_payload_charisk, main_ctrl_sink_payload_data,
                main_ctrl_source_payload_data, main_ctrl_source_payload_charisk})
);


