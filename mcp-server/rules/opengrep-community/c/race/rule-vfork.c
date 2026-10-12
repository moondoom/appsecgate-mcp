// License: MIT (c) GitLab Inc.

#include<stdio.h>

#include<unistd.h>

int main(void) {

  printf("First stmt\n");
  // ruleid: c_race_rule-vfork
  vfork();
  printf("Last Stmt\n");

}
