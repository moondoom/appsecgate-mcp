// License: MIT (c) GitLab Inc.
#include <stdio.h>

void main() {
  // ruleid: c_misc_rule-LoadLibraryEx
  (void) LoadLibraryEx(L "user32.dll", nullptr, LOAD_LIBRARY_AS_DATAFILE);
}
