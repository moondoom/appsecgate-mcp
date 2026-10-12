// License: MIT (c) GitLab Inc.
#include <unistd.h>

void main() {
  unsigned int millis = 500000;
  // ruleid: c_obsolete_rule-usleep
  int expect = usleep(millis);

}
