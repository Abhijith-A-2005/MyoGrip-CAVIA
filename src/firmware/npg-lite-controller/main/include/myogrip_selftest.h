#ifndef MYOGRIP_SELFTEST_H
#define MYOGRIP_SELFTEST_H

/*
 * Set to 0 and rebuild to disable automatic simulated events.
 * Never enable this test task in a motor-driving build.
 */
#define MYOGRIP_SELFTEST_ENABLED 0

void myogrip_selftest_start(void);

#endif