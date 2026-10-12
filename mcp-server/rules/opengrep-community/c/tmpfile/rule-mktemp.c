// License: MIT (c) GitLab Inc.
#include <stdlib.h>

void main() {

  char * original = "/tmp/name_idk";
  char * newloc;
  // ruleid: c_tmpfile_rule-mktemp
  newloc = mktemp(original);
  return 0;

}
