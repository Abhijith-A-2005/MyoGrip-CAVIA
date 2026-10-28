#include <assert.h>
#include <math.h>
#include <stdio.h>
#include "myogrip_live.h"
#include "emg_config.h"
static uint64_t now;
static mg_menu_t menu = {.menu_id=42, .adaptive={MG_GRIP_LATERAL,MG_GRIP_PINCH},
    .adaptive_count=2, .full={MG_GRIP_POWER,MG_GRIP_PINCH,MG_GRIP_TRIPOD,MG_GRIP_LATERAL}, .full_count=4};
static void sample(myogrip_live_t *live, mg_keyboard_t *keys, const char *activity, emg_gesture_t event) {
    myogrip_live_sample_shared(live,keys,now,activity,event); now += 4;
}
static void key(mg_keyboard_t *keys, unsigned mask) {
    assert(mg_keyboard_receive(keys,keys->session,keys->sequence+1,(uint8_t)mask,now));
}
static void prep(myogrip_live_t *live, mg_keyboard_t *keys, bool armed) {
    now=1000; myogrip_live_init(live); mg_keyboard_init(keys);
    assert(mg_keyboard_receive(keys,1,1,0,now));
    if(armed) for(unsigned i=0;i<EMG_EPISODE_REST_SAMPLES;i++) sample(live,keys,"REST",EMG_GESTURE_NONE);
    assert(myogrip_live_load_menu(live,&menu,live->revision,false));
}
static bool near(float a,float b) { return fabsf(a-b)<0.00001f; }
int main(void) {
    myogrip_live_t live; mg_keyboard_t keys;
    prep(&live,&keys,false);
    key(&keys,MG_KEY_S); key(&keys,0);
    assert(!myogrip_live_menu_ready_shared(&live,&keys));
    sample(&live,&keys,"UNCALIBRATED",EMG_GESTURE_NONE);
    assert(live.fsm.selected==1 && live.gesture_seq==1 && !live.armed && !live.calibrated);
    for(unsigned i=0;i<120;i++) sample(&live,&keys,"UNCALIBRATED",EMG_GESTURE_NONE);
    assert(live.fsm.state==MG_ADAPTIVE && live.fsm.selected==1 && live.gesture_seq==1);
    puts("PASS: short taps and persistent menus without calibration");

    prep(&live,&keys,true);
    key(&keys,MG_KEY_S);
    sample(&live,&keys,"REST",EMG_GESTURE_SF);
    assert(live.fsm.selected==1 && live.gesture_seq==1);
    assert(live.gesture_source[0]=='b');
    key(&keys,MG_KEY_S); sample(&live,&keys,"REST",EMG_GESTURE_NONE);
    assert(live.fsm.selected==1 && live.gesture_seq==1);
    puts("PASS: matching navigation events merge once; heartbeat does not repeat them");

    prep(&live,&keys,true); key(&keys,MG_KEY_S);
    sample(&live,&keys,"REST",EMG_GESTURE_SE);
    assert(live.fsm.selected==0 && live.last_gesture==EMG_GESTURE_REJECTED);
    puts("PASS: opposing navigation does not confirm or move selection");

    prep(&live,&keys,true); key(&keys,MG_KEY_A);
    sample(&live,&keys,"FLEX_ACTIVE",EMG_GESTURE_LF);
    assert(live.fsm.state==MG_CLOSING && near(live.fsm.grip_progress,0.001f));
    for(unsigned i=0;i<20;i++) sample(&live,&keys,"FLEX_ACTIVE",EMG_GESTURE_NONE);
    assert(near(live.fsm.grip_progress,0.021f));
    key(&keys,0); sample(&live,&keys,"FLEX_ACTIVE",EMG_GESTURE_NONE);
    assert(live.fsm.state==MG_CLOSING && near(live.fsm.grip_progress,0.022f));
    key(&keys,MG_KEY_D); sample(&live,&keys,"FLEX_ACTIVE",EMG_GESTURE_NONE);
    assert(live.fsm.state==MG_HOLDING && live.fsm.wait_release);
    assert(near(live.fsm.grip_progress,0.022f));
    key(&keys,0); sample(&live,&keys,"FLEX_ACTIVE",EMG_GESTURE_NONE);
    assert(live.fsm.wait_release);
    sample(&live,&keys,"REST",EMG_GESTURE_NONE);
    assert(!live.fsm.wait_release);
    sample(&live,&keys,"FLEX_ACTIVE",EMG_GESTURE_NONE);
    assert(live.fsm.state==MG_CLOSING);
    puts("PASS: combined closing speed, EMG continuation, conflict hold and release gate");

    prep(&live,&keys,true); key(&keys,MG_KEY_A);
    for(unsigned i=0;i<30;i++) sample(&live,&keys,"FLEX_ACTIVE",i==0?EMG_GESTURE_LF:EMG_GESTURE_NONE);
    key(&keys,MG_KEY_A|MG_KEY_E);
    sample(&live,&keys,"FLEX_ACTIVE",EMG_GESTURE_LF);
    assert(live.fsm.returning && live.fsm.state==MG_OPENING);
    key(&keys,0);
    for(unsigned i=0;i<100 && live.fsm.returning;i++) sample(&live,&keys,"FLEX_ACTIVE",EMG_GESTURE_LF);
    assert(live.fsm.state==MG_FULL && !live.fsm.returning && live.fsm.active_grip==MG_GRIP_NONE);
    puts("PASS: HE priority and uninterrupted controlled return");

    prep(&live,&keys,false); key(&keys,MG_KEY_A);
    sample(&live,&keys,"UNCALIBRATED",EMG_GESTURE_NONE);
    key(&keys,0); sample(&live,&keys,"UNCALIBRATED",EMG_GESTURE_NONE);
    key(&keys,MG_KEY_A|MG_KEY_D); sample(&live,&keys,"UNCALIBRATED",EMG_GESTURE_NONE);
    assert(live.fsm.state==MG_HOLDING && live.fsm.wait_release);
    key(&keys,0); sample(&live,&keys,"UNCALIBRATED",EMG_GESTURE_NONE);
    assert(!live.fsm.wait_release);
    puts("PASS: conflicting keyboard directions hold until release");

    prep(&live,&keys,false); key(&keys,MG_KEY_A);
    sample(&live,&keys,"UNCALIBRATED",EMG_GESTURE_NONE);
    assert(live.fsm.state==MG_CLOSING);
    float progress=live.fsm.grip_progress;
    now=1400; sample(&live,&keys,"UNCALIBRATED",EMG_GESTURE_NONE);
    assert(!keys.connected && live.fsm.state==MG_HOLDING && near(progress,live.fsm.grip_progress));
    for(unsigned i=0;i<100;i++) sample(&live,&keys,"UNCALIBRATED",EMG_GESTURE_NONE);
    assert(live.fsm.state==MG_HOLDING && near(progress,live.fsm.grip_progress));
    assert(!mg_keyboard_receive(&keys,1,keys.sequence+1,MG_KEY_A,now));
    key(&keys,0); key(&keys,MG_KEY_A); sample(&live,&keys,"UNCALIBRATED",EMG_GESTURE_NONE);
    assert(live.fsm.state==MG_CLOSING);
    puts("PASS: timeout stops keyboard-only movement and requires release to resume");

    prep(&live,&keys,false); key(&keys,MG_KEY_S);
    myogrip_live_gap(&live); mg_keyboard_invalidate(&keys);
    sample(&live,&keys,"UNCALIBRATED",EMG_GESTURE_NONE);
    assert(live.fsm.state==MG_HOME && !keys.mask && keys.pending==MG_KEY_EVENT_NONE);
    assert(!mg_keyboard_receive(&keys,1,keys.sequence+1,MG_KEY_A,now));
    key(&keys,0);
    assert(myogrip_live_load_menu(&live,&menu,live.revision,false));
    key(&keys,MG_KEY_S); sample(&live,&keys,"UNCALIBRATED",EMG_GESTURE_NONE);
    assert(live.fsm.selected==1);
    puts("PASS: acquisition reset discards pending keys; released keyboard can recover");
    return 0;
}
