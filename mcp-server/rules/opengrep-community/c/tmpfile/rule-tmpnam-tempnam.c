// License: MIT (c) GitLab Inc.
#include <stdio.h>

#include <stdlib.h>

int main() {
  char filenamegen[L_tmpnam + 1];
  // ruleid: c_tmpfile_rule-tmpnam-tempnam
  tmpnam(filenamegen);
  // ruleid: c_tmpfile_rule-tmpnam-tempnam
  tempnam("/users", "file");
  return 0;
}
