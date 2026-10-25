"""Panduit driver 1.3.0.25 GPD limits; HD is single-sided here.

HD's 2497-dot logical page combines two heads, not a 211 mm physical head.
Do not use that combined page with the existing side-by-side label templates.
"""
from typing import Literal

PrinterModel = Literal['custom', 'DP4300M', 'DP4300H', 'DP4600H', 'DP4300HD', 'TDP43ME']
# Native DPI, usable dots for one head. From extracted GPDs; HD uses one head.
PROFILES = {
    'TDP43ME': (300, 1248),  # Conservative whole-byte width below 105.7 mm.
    'DP4300M': (300, 1249),
    'DP4300H': (300, 1249),
    'DP4600H': (600, 2497),
    'DP4300HD': (300, 1249),
}
