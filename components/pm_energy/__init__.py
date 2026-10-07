"""The JXD-PM meters' energy counter records in fram_store_counters, for the energy packages' lambdas."""

import esphome.config_validation as cv

CODEOWNERS = ["@jethome-iot"]
DEPENDENCIES = ["fram_store"]

# Nothing to configure and no code to generate: the key only brings pm_energy.h into the build,
# so jxd-pm220-energy.yaml and jxd-pm380-energy.yaml share one definition of each record.
CONFIG_SCHEMA = cv.Schema({})
