// License: MIT (c) GitLab Inc.
#include<stdio.h>

#include<stdlib.h>

#include<unistd.h>

void main() {
  char * buf;
  buf = (char * ) malloc(4 * sizeof(char));
  // ruleid: c_misc_rule-getlogin
  buf = getlogin();
  printf(" %s", buf);
}
