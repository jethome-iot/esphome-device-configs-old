#pragma once

#include <cinttypes>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <type_traits>
#include "esphome/components/fram_store/fram_region.h"
#include "esphome/core/log.h"

namespace esphome::pm_energy {

// The JXD-PM meters keep their energy counters in fram_store_counters of features/fram.yaml, one
// record per 48-byte slot:
//
//   fram_counter_00-02  Energy Counter 1-3                                    CounterRecord
//   fram_counter_03     Energy Today, Yesterday, This Month and Last Month    PeriodsRecord
//   fram_counter_04-09  Energy Channel 1-6 with its BL0906 reading, PM220     CounterRecord
//   fram_counter_10-15  free
//
// fram_store keeps two copies of a slot and moves to the new one only once it is written whole, so
// a power cut costs the save it interrupted, never the value before it. A pass that saves several
// slots is not atomic as a whole: jxd-pm220-energy.yaml orders its saves so that a cut between two
// of them loses part of a pass instead of counting it twice.
//
// Every record starts with its kind and version. A firmware that finds a record it does not read
// starts that counter from zero rather than take foreign bytes for energy, and overwrites it at its
// next save.

static const char *const TAG = "pm_energy";
static constexpr size_t RECORD_SIZE = 48;

// One counter: the energy since its last reset, and when that was.
struct CounterRecord {
  static constexpr uint32_t MAGIC = 0x504D4354;  // "PMCT"
  static constexpr uint16_t VERSION = 1;

  uint32_t magic;
  uint16_t version;
  uint16_t reserved0;
  double wh;
  // UTC; 0 until the clock was first valid, from when the counter then counts.
  uint32_t reset_time;
  // The chip's own reading, in kWh, that wh was last brought up to; NAN while unknown, which makes
  // the next reading the starting point. Kept only by a counter fed from a chip register that runs
  // on across ESP reboots (a PM220 channel): in the counter's own record, the two never disagree.
  float chip_kwh;
  uint8_t reserved[24];

  static CounterRecord of(double wh, uint32_t reset_time, float chip_kwh = NAN) {
    CounterRecord record{};
    record.magic = MAGIC;
    record.version = VERSION;
    record.wh = wh;
    record.reset_time = reset_time;
    record.chip_kwh = chip_kwh;
    return record;
  }
  static CounterRecord blank() { return of(0, 0); }
};

// The calendar counters, in one record so a day or month rollover is saved whole.
struct PeriodsRecord {
  static constexpr uint32_t MAGIC = 0x504D5044;  // "PMPD"
  static constexpr uint16_t VERSION = 1;

  uint32_t magic;
  uint16_t version;
  uint16_t reserved0;
  double today_wh;
  double yesterday_wh;
  double month_wh;
  double last_month_wh;
  // The day (year * 1000 + day of year) and the month (year * 12 + month - 1) that today_wh and
  // month_wh count; 0 before the clock was first valid.
  uint32_t day_key;
  uint32_t month_key;

  static PeriodsRecord blank() {
    PeriodsRecord record{};
    record.magic = MAGIC;
    record.version = VERSION;
    return record;
  }
};

static_assert(sizeof(CounterRecord) == RECORD_SIZE, "CounterRecord must fill a fram_counter slot");
static_assert(sizeof(PeriodsRecord) == RECORD_SIZE, "PeriodsRecord must fill a fram_counter slot");
static_assert(std::is_trivially_copyable<CounterRecord>::value, "fram_store copies records byte for byte");
static_assert(std::is_trivially_copyable<PeriodsRecord>::value, "fram_store copies records byte for byte");

// Loads the records of one pass and counts how it went. Nothing may be counted or saved while any
// slot failed: its record is still in FRAM, unread, and a save would bury it.
struct LoadTally {
  uint8_t loaded{0};
  uint8_t blank{0};
  uint8_t failed{0};

  // Leaves the slot's record in `record`, or blank() when the slot holds nothing this firmware reads.
  template<typename T> void load(fram_store::FramSlot *slot, T &record) {
    // A slot that could not be read at boot never loads and refuses every save.
    if (!slot->is_initialised()) {
      this->failed++;
      return;
    }
    if (slot->has_data()) {
      if (!slot->load(record)) {
        this->failed++;
        return;
      }
      if (record.magic == T::MAGIC && record.version == T::VERSION) {
        this->loaded++;
        return;
      }
      ESP_LOGW(TAG, "Slot at 0x%04X holds record 0x%08" PRIX32 " v%u, which this firmware does not read",
               slot->offset(), record.magic, record.version);
    }
    record = T::blank();
    this->blank++;
  }
};

// Saves `record` unless `saved`, the image the slot last took, already equals it, so a pass that
// changed nothing writes nothing. `saved` follows only a save that went through.
template<typename T> bool save_record(fram_store::FramSlot *slot, const T &record, T &saved) {
  if (std::memcmp(&record, &saved, sizeof(T)) == 0)
    return true;
  if (!slot->save(record))
    return false;
  saved = record;
  return true;
}

}  // namespace esphome::pm_energy
