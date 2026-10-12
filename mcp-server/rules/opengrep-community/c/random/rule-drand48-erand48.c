// License: MIT (c) GitLab Inc.

#include<stdio.h>

#include <stdlib.h>

#include <time.h>

#include <string.h>

int main() {
  short example[4];
  int i;
  // ruleid: c_random_rule-drand48-erand48
  short * seed48(short * );
  char * str = (char * ) malloc(sizeof(char) * 11);
  char * ptr;

  // ruleid: c_random_rule-drand48-erand48
  double a = drand48();
  // ruleid: c_random_rule-drand48-erand48
  double b = erand48(example);
  // ruleid: c_random_rule-drand48-erand48
  long b = jrand48(example);
  // ruleid: c_random_rule-drand48-erand48
  void lcong48();
  // ruleid: c_random_rule-drand48-erand48
  lcong48(example);
  // ruleid: c_random_rule-drand48-erand48
  long d = lrand48();
  // ruleid: c_random_rule-drand48-erand48
  long z = mrand48();
  // ruleid: c_random_rule-drand48-erand48
  long t = nrand48(example);

  // ruleid: c_random_rule-drand48-erand48
  srand(time(0));
  for (int i = 0; i < 2; i++)
    printf(" %d ", rand());

  // ruleid: c_random_rule-drand48-erand48
  oldptr = seed48(newseed);
  for (i = 0; i < 10; i++) {
    // ruleid: c_random_rule-drand48-erand48
    ptr = (char * ) strfry(str);
    printf("Random numbers are: #%d: %s\n", i, ptr);
  }

}
