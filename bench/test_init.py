#!/usr/bin/env python3

#
# This file is part of LiteSATA.
#
# Copyright (c) 2015-2020 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import time
from litex import RemoteClient

wb   = RemoteClient()
wb.open()

wb.regs.sata_phy_enable.write(0)
time.sleep(1)
wb.regs.sata_phy_enable.write(1)
print("PHY re-init")

wb.close()
