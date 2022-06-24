#include "current_shaper.h"

CurrentShaperTask *CurrentShaperTask::instance = NULL;

CurrentShaperTask::CurrentShaperTask() : MicroTasks::Task() {
	_changed = false;
	_enabled = false;
}

CurrentShaperTask::~CurrentShaperTask() {
	instance = NULL;
}

void CurrentShaperTask::setup() {

}

unsigned long CurrentShaperTask::loop(MicroTasks::WakeReason reason) {
	if (_enabled) {
			EvseProperties props;
			if (_changed) {
				props.setChargeCurrent(_chg_cur);
				props.setState(EvseState::None);
				_changed = false;
				_timer = millis();
				evse.claim(EvseClient_OpenEVSE_Shaper,EvseManager_Priority_Limit, props);
				StaticJsonDocument<128> event;
				event["shaper"]  = 1;
				event["shaper_live_pwr"] = _live_pwr;
				event["shaper_cur"]	     = _chg_cur;
				event_send(event);
			}
			if (millis() - _timer > EVSE_SHAPER_FAILSAFE_TIME) {
				//available power has not been updated since EVSE_SHAPER_FAILSAFE_TIME, pause charge
				DBUGF("MQTT avl_pwr has not been updated in time, pausing charge");
				props.setState(EvseState::Disabled);
				evse.claim(EvseClient_OpenEVSE_Shaper,EvseManager_Priority_Limit, props);

				StaticJsonDocument<128> event;
				event["shaper"]  = 1;
				event["shaper_live_pwr"] = _live_pwr;
				event["shaper_cur"]	     = _chg_cur;
				event_send(event);
			}
	}
	
	
	return EVSE_SHAPER_LOOP_TIME;
}

void CurrentShaperTask::begin(EvseManager &evse) {
	this -> _timer   = millis();
	this -> _enabled = config_current_shaper_enabled();
	this -> _evse    = &evse;
	this -> _max_pwr = current_shaper_max_pwr; 
	this -> _live_pwr = 0;
	this -> _chg_cur = 0; 
	instance = this;
	MicroTask.startTask(this);
	StaticJsonDocument<128> event;
	event["shaper"]  = 1;
	event_send(event);
}

void CurrentShaperTask::notifyConfigChanged( bool enabled, uint32_t max_pwr) {
    if (instance) {
		DBUGF("CurrentShaper: got config changed");
        instance->_enabled = enabled;
		instance->_max_pwr = max_pwr;
		if (!enabled) evse.release(EvseClient_OpenEVSE_Shaper);
		StaticJsonDocument<128> event;
		event["shaper"] = enabled;
		event["shaper_max_pwr"] = max_pwr;
		event_send(event);
    }
}

void CurrentShaperTask::setMaxPwr(int max_pwr) {
	if (instance) {
		instance -> _max_pwr = max_pwr;
		instance -> shapeCurrent();
	}
}

void CurrentShaperTask::setLivePwr(int live_pwr) {
	if (instance) {
		instance -> _live_pwr = live_pwr;
		instance -> shapeCurrent();
	}
}

// temporary change Current Shaper state without changing configuration 
void CurrentShaperTask::setState(bool state) {
	if (instance) {
		instance -> _enabled = state;
		StaticJsonDocument<128> event;
		event["shaper"]  = state?1:0;
		event_send(event);
	}
}

void CurrentShaperTask::shapeCurrent() {
	if (instance) {
		instance -> _chg_cur = round((_max_pwr - _live_pwr + evse.getAmps()) / evse.getVoltage());
		instance -> _changed = true; // update claim in the loop
	}
}

int CurrentShaperTask::getMaxPwr() {
	if (instance) {
		return instance -> _max_pwr;
	}
	else return 0;
}
int CurrentShaperTask::getLivePwr() {
	if (instance) {
		return instance -> _live_pwr;
	}
	else return 0;
}
uint8_t CurrentShaperTask::getChgCur() {
	if (instance) {
		return instance -> _chg_cur;
	}
	else return 0;
}
bool CurrentShaperTask::getState() {
	if (instance) {
		return instance -> _enabled;
	}
	else return 0;
}

bool CurrentShaperTask::isActive() {
	if (instance) {
		return instance -> _evse->clientHasClaim(EvseClient_OpenEVSE_Shaper);
    }
	else return false;
}