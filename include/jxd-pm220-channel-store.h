#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

#include "esphome/core/helpers.h"

// PM220 per-channel state in FRAM: the user channel counters and the BL0906 channel readings
// (kWh) at the last counting pass. The chip counters keep running across ESP reboots, so with
// the readings kept the counters resume from the right place and also get what the chip counted
// while the ESP was down. One record, so a counter and its starting point never disagree.
// Fields are ordered so the struct has no padding and the CRC covers defined bytes only.
struct ChannelEnergyStore {
  std::array<double, 6> channel_wh;
  std::array<float, 6> chip_kwh;
  std::array<uint32_t, 6> channel_time;
  uint32_t magic;
  uint16_t version;
  uint16_t crc;
};
static_assert(sizeof(ChannelEnergyStore) == 104, "ChannelEnergyStore layout changed, bump CHANNEL_STORE_VERSION");

static const uint32_t CHANNEL_STORE_MAGIC = 0x424C3036;  // "BL06"
// 1 held only the chip readings
static const uint16_t CHANNEL_STORE_VERSION = 2;
// After the EnergyStore image at 0x0100, with room for it to grow
static const uint16_t CHANNEL_STORE_ADDRESS = 0x0180;

inline uint16_t channel_store_crc(const ChannelEnergyStore &store) {
  return esphome::crc16(reinterpret_cast<const uint8_t *>(&store), offsetof(ChannelEnergyStore, crc));
}
