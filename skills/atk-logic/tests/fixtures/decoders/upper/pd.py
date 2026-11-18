"""Upstream test decoder: turns edges into OUTPUT_PYTHON packets."""

import sigrokdecode as srd


class Decoder(srd.Decoder):
    api_version = 3
    id = 'upper'
    name = 'Upper'
    longname = 'Upper test decoder'
    desc = 'Emits one packet per edge; used to test decoder stacking.'
    license = 'apache2'
    inputs = ['logic']
    outputs = ['upper']
    channels = ({'id': 'a', 'name': 'A', 'desc': 'Signal'},)
    annotations = (('edge', 'Edge'),)

    def start(self):
        self.out_py = self.register(srd.OUTPUT_PYTHON)

    def decode(self):
        while True:
            pins = self.wait({0: 'e'})
            self.put(self.samplenum, self.samplenum, self.out_py, ['EDGE', pins[0]])
