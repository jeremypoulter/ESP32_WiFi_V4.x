#include "current_shaper.h"

CurrentShaperTask *CurrentShaperTask::instance = NULL;

CurrentShaperTask::CurrentShaperTask() : MicroTasks::Task() {
	_changed = false;
}

CurrentShaperTask::~CurrentShaperTask() {
	evse.release(EvseClient_OpenEVSE_Shaper);
	instance = NULL;
	StaticJsonDocument<128> event;
	event["shaper_enabled"] = false;
	event_send(event);
}

void CurrentShaperTask::setup() {

}

unsigned long CurrentShaperTask::loop(MicroTasks::WakeReason reason) {
	if (config_current_shaper_enabled()) {
		EvseProperties props;
		if (_changed) {
			props.setChargeCurrent(_chg_cur);
			props.setState(EvseState::Active);
			_changed = false;
			_timer = millis();
			evse.claim(EvseClient_OpenEVSE_Shaper,EvseManager_Priority_Shaper, props);
		}
		if (millis() - _timer < EVSE_SHAPER_FAILSAFE_TIME) {
			//available power has not been updated since EVSE_SHAPER_FAILSAFE_TIME, pause charge
			DBUGF("MQTT avl_pwr has not bee updated in time, pausing charge");
			props.setState(EvseState::Disabled);
			evse.claim(EvseClient_OpenEVSE_Shaper,EvseManager_Priority_Shaper, props);

			StaticJsonDocument<128> event;
			event["shaper_enabled"]  = true;
			event["shaper_max_pwr"]  = _max_pwr;
			event["shaper_live_pwr"] = _live_pwr;
			event["shaper_cur"]	     = _chg_cur;
			event_send(event);
		}
	}
	
	
	return EVSE_SHAPER_LOOP_TIME;
}

void CurrentShaperTask::begin(EvseManager &evse) {
	this -> _timer   = millis();
	this -> _evse    = &evse;
	this -> _max_pwr = evse.getMaxCurrent(); // default to MaxCurrent
	this -> _live_pwr = 0;
	this -> _chg_cur = 0; 
	instance = this;
	
	StaticJsonDocument<128> event;
	event["shaper_enabled"]  = true;
	event["shaper_max_pwr"]  = _max_pwr;
	event["shaper_live_pwr"] = _live_pwr;
	event["shaper_cur"]	     = _chg_cur;
	event_send(event);
}

void CurrentShaperTask::reconfigure() {

}

void CurrentShaperTask::setMaxPwr(int max_pwr) {
	_max_pwr = max_pwr;
	shapeCurrent();
}

void CurrentShaperTask::setLivePwr(int live_pwr) {
	_live_pwr = live_pwr;
	shapeCurrent();
}

void CurrentShaperTask::shapeCurrent() {
	_chg_cur = round((_max_pwr - _live_pwr + evse.getAmps()) / evse.getVoltage());
	_changed = true; // update claim in the loop
}

int CurrentShaperTask::getMaxPwr() {
	return _max_pwr;
}
int CurrentShaperTask::getLivePwr() {
	return _live_pwr;
}