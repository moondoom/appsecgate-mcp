// License: MIT (c) GitLab Inc.
#include <stdio.h>

#include <stdlib.h>

#include <string.h>

int main() {
  char command[50];
  strcpy(command, "ls -l");
  // ruleid: c_shell_rule-system
  system(command);
  return (0);
}
