#include "codec_old.h"

namespace old { namespace legacy {
int load(int x) { return x; }
} }

namespace old { namespace legacy { namespace v1 {
int load(int x) { return x * 2; }  // nested one level deeper than the call names
} } }
