// License: MIT (c) GitLab Inc.

#include <stdlib.h>

void main(void) {

  char temp[] = "/tmp/filename_123456789";
  // ruleid: c_tmpfile_rule-mkstemp
  int loc = mkstemp(temp);

}
