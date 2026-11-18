"""A minimal sigrok-compatible decoder used to test the host.

It is written here (not copied from the vendor) so the host can be tested
without an ATK-Logic installation: one channel, one option, one annotation row,
and the two behaviours the vendor fork relies on — ``wait()`` returns the
signal levels and ``self.matched`` is indexed per condition.
"""

import sigrokdecode as srd


class Decoder(srd.Decoder):
    api_version = 3
    id = 'mini'
    name = 'Mini'
    longname = 'Mini test decoder'
    desc = 'Emits the level of every edge and the configured threshold.'
    license = 'apache2'
    inputs = ['logic']
    outputs = []
    channels = ({'id': 'a', 'name': 'A', 'desc': 'Signal'},)
    options = ({'id': 'threshold', 'desc': 'Threshold', 'default': 2},)
    annotations = (('level', 'Level'), ('option', 'Option'))
    annotation_rows = (
        ('levels', 'Levels', (0,)),
        ('options', 'Options', (1,)),
    )

    def start(self):
        self.out = self.register(srd.OUTPUT_ANN)

    def decode(self):
        self.put(0, 0, self.out, [1, [f"threshold={self.options['threshold']}"]])
        while True:
            pins = self.wait({0: 'e'})
            if self.matched[0]:
                self.put(self.samplenum, self.samplenum, self.out, [0, [str(pins[0])]])
