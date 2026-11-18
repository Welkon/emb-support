"""Downstream test decoder: consumes the upstream decoder's packets."""

import sigrokdecode as srd


class Decoder(srd.Decoder):
    api_version = 3
    id = 'lower'
    name = 'Lower'
    longname = 'Lower test decoder'
    desc = 'Consumes packets from the upper decoder; used to test stacking.'
    license = 'apache2'
    inputs = ['upper']
    outputs = []
    annotations = (('packet', 'Packet'),)
    annotation_rows = (('packets', 'Packets', (0,)),)

    def start(self):
        self.out = self.register(srd.OUTPUT_ANN)

    def decode(self, ss, es, data):
        kind, level = data
        self.put(ss, es, self.out, [0, [f"{kind} {level}"]])
