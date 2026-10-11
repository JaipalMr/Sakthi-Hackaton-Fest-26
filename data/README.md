# Dataset documentation - `festival_transport_demand.csv`

> **THIS DATASET IS SYNTHETIC.** It was produced by `python -m ml.generate_dataset` (fixed seed `20250615`).
> It does **not** represent real observations, a real transit network or a real festival. Target labels exist
> only to demonstrate the pipeline; any accuracy measured on them says nothing about real-world performance.

**Size:** exactly 15,000 data rows (excluding header) = 5 festivals x 6 days x 50 slots (15 min, 12:00-00:15) x 10 stops.
**Key:** (`timestamp`, `festival_id`, `stop_id`) is unique. Regenerating yields a byte-identical file.
Validate with `python -m ml.validate_dataset`.

## Columns
| column | meaning |
|---|---|
| timestamp | local slot start, ISO 8601, no timezone |
| festival_id, festival_day | synthetic festival edition (Jan/Apr/Jul/Sep/Nov 2025) and day 1-6 |
| scheduled_start_time / scheduled_end_time | event schedule for that day (start 15:00-16:30, end 21:30-23:00) |
| festival_attendance | assumed attendance of the edition (9,500-13,500) |
| stop_id, stop_name, latitude, longitude | fictional stop; coordinates are placeholders around an arbitrary origin |
| stop_capacity | assumed people the waiting area holds (operational assumption) |
| event_phase | pre_event / arrival / main_event / dispersal / wind_down, derived from the schedule |
| weather_condition, temperature, rainfall | simulated weather (rainfall mm/h) |
| route_closed | 1 while the stop's route is closed (about 1% of rows) |
| historical_or_observed_passengers | passenger count of the **previous** slot (the only demand-derived input; lag-1) |
| available_buses, average_bus_capacity | buses planned at the stop and their typical capacity (45/60/75 +-5) |
| average_wait_time | minutes, measured over the previous slot (excluded from model features) |
| route_travel_time | in-service route minutes, affected by congestion, rain, closures |
| target_passenger_demand | passengers wanting to board at the stop in this slot (the label) |
| data_source | always `synthetic` |

## Generating assumptions (documented, simplified)
* Demand = riders x (arrival share x arrival curve + dispersal share x dispersal curve) + local background, then Poisson noise with
  stop-day random effects and AR(1) slot noise. Arrivals peak ~45 min before start (hub stops); dispersal is a gamma-shaped
  wave after the end (venue stops) plus 15% steady early leavers.
* Rain raises bus use (+3.5% per mm/h up to 12) and travel time (+1.2% per mm/h); heat above 33 C adds ridership.
* Weekends are busier (Sat x1.2, Sun x1.15); later festival days ramp slightly.
* Fleet plan follows a *mis-estimated, time-shifted* version of expected demand plus random breakdowns, so allocation is
  imperfect - the situation the optimiser is meant to improve.
* Closure: buses x0.5, travel time x1.6, demand x0.8 at the stop; **no spill-over** to neighbouring stops is modelled.
* Throughput per slot = buses x capacity x min(1, 15 / (2 x route_time + 8)).
* Wait time and the lag count are built from the previous slot, so no current-slot target leaks into features.
