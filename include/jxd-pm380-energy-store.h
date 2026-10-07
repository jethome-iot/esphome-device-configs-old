#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

#include "esphome/core/helpers.h"

// PM380 energy counters, kept in the CPU board FRAM instead of flash: FRAM takes a write
// every few seconds for the life of the device, so a power cut costs seconds of counting.
// Fields are ordered so the struct has no padding and the CRC covers defined bytes only.
struct EnergyStore {
  std::array<double, 3> slot_wh;
  double today_wh;
  double yesterday_wh;
  double month_wh;
  double last_month_wh;
  std::array<uint32_t, 3> slot_time;
  uint32_t day_key;
  uint32_t month_key;
  uint32_t reserved;
  uint32_t magic;
  uint16_t version;
  uint16_t crc;
};
static_assert(sizeof(EnergyStore) == 88, "EnergyStore layout changed, bump ENERGY_STORE_VERSION");

static const uint32_t ENERGY_STORE_MAGIC = 0x504D3338;  // "PM38"
static const uint16_t ENERGY_STORE_VERSION = 1;
// Clear of the byte the FRAM self-test writes at 0x0001
static const uint16_t ENERGY_STORE_ADDRESS = 0x0100;

inline uint16_t energy_store_crc(const EnergyStore &store) {
  return esphome::crc16(reinterpret_cast<const uint8_t *>(&store), offsetof(EnergyStore, crc));
}
