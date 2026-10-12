// License: MIT (c) GitLab Inc.

#include <malloc.h>

#include<stdio.h>

void main(void) {
  int align = 5;
  int size = 10;
  // ruleid: c_free_rule-memalign
  void * memalign;
  void * ptr;

  // ruleid: c_free_rule-memalign
  ptr = memalign(align, size);
}
