// License: MIT (c) GitLab Inc.

#include <unistd.h>

void main() {

  char temp[1024];
  // ruleid: c_race_rule-readlink
  readlink("/modules/pass1", temp, sizeof(temp) - 1);
  return 0;

}
