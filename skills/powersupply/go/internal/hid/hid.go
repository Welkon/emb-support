package hid

// Transport is one 64-byte HID report channel.
type Transport interface {
	Write([]byte) error
	Read(n int, timeoutMS int) ([]byte, error)
	Close() error
	Path() string
}
