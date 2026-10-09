#include "codec_old.h"

namespace app { namespace legacy {
int load(int x)
{
    // same name and same innermost namespace as the target, but a different outer one
    return old::legacy::load(x) + 1;
}
} }
