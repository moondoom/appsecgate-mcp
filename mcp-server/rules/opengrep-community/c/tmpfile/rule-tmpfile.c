// License: MIT (c) GitLab Inc.

#include <stdio.h>

int main() {
  char string[] = "Hola amigo";
  int i = 0;
  // ruleid: c_tmpfile_rule-tmpfile
  FILE * tmp = tmpfile();
  puts("Temporary file is created\n");
  while (string[i] != '\0') {
    fputc(string[i], tmp);
    i++;
  }
  return 0;
}
