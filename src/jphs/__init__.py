"""Pure-Python port of jphs (Hide & Seek 0.3) by Allan Latham.

jphide hides a file inside the quantized DCT coefficients of a JPEG, and
jpseek recovers it.  Coefficient selection is driven by four Blowfish
keystreams seeded from the first DCT block of the cover image, so the
payload can only be recovered from the stego image itself.
"""

__version__ = "0.3.0"

HS_MAJOR_VERSION = 0
HS_MINOR_VERSION = 3
