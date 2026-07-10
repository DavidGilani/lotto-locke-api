-- Fix HGSS boss names: rename city/location values to trainer short names
-- so they match the section short names used by the frontend and handler.py.
--
-- Run this in the Supabase SQL editor.
-- Safe to run multiple times (updates are idempotent).
-- VERIFY the old names in the left column match what's actually in your bosses table
-- before running — you can check with: SELECT DISTINCT boss FROM bosses WHERE version IN ('HeartGold','SoulSilver','BothHGSS');

-- Johto gyms
UPDATE bosses SET boss = 'Falkner' WHERE boss = 'Violet City'     AND version IN ('HeartGold','SoulSilver','BothHGSS');
UPDATE bosses SET boss = 'Bugsy'   WHERE boss = 'Azalea Town'     AND version IN ('HeartGold','SoulSilver','BothHGSS');
UPDATE bosses SET boss = 'Whitney' WHERE boss = 'Goldenrod City'  AND version IN ('HeartGold','SoulSilver','BothHGSS');
UPDATE bosses SET boss = 'Morty'   WHERE boss = 'Ecruteak City'   AND version IN ('HeartGold','SoulSilver','BothHGSS');
UPDATE bosses SET boss = 'Chuck'   WHERE boss = 'Cianwood City'   AND version IN ('HeartGold','SoulSilver','BothHGSS');
UPDATE bosses SET boss = 'Jasmine' WHERE boss = 'Olivine City'    AND version IN ('HeartGold','SoulSilver','BothHGSS');
UPDATE bosses SET boss = 'Pryce'   WHERE boss = 'Mahogany Town'   AND version IN ('HeartGold','SoulSilver','BothHGSS');
UPDATE bosses SET boss = 'Clair'   WHERE boss = 'Blackthorn City' AND version IN ('HeartGold','SoulSilver','BothHGSS');

-- Kanto gyms (visited post-game in HGSS)
UPDATE bosses SET boss = 'Surge'   WHERE boss = 'Vermilion City'  AND version IN ('HeartGold','SoulSilver','BothHGSS');
UPDATE bosses SET boss = 'Erika'   WHERE boss = 'Celadon City'    AND version IN ('HeartGold','SoulSilver','BothHGSS');
UPDATE bosses SET boss = 'Sabrina' WHERE boss = 'Saffron City'    AND version IN ('HeartGold','SoulSilver','BothHGSS');
UPDATE bosses SET boss = 'Janine'  WHERE boss = 'Fuchsia City'    AND version IN ('HeartGold','SoulSilver','BothHGSS');
UPDATE bosses SET boss = 'Misty'   WHERE boss = 'Cerulean City'   AND version IN ('HeartGold','SoulSilver','BothHGSS');
UPDATE bosses SET boss = 'Brock'   WHERE boss = 'Pewter City'     AND version IN ('HeartGold','SoulSilver','BothHGSS');
UPDATE bosses SET boss = 'Blaine'  WHERE boss = 'Cinnabar Island' AND version IN ('HeartGold','SoulSilver','BothHGSS');
UPDATE bosses SET boss = 'Blue'    WHERE boss = 'Viridian City'   AND version IN ('HeartGold','SoulSilver','BothHGSS');

-- Elite Four (Johto Indigo Plateau — stored per trainer name)
-- Will, Koga, Bruno, Karen should already be correct trainer names.
-- Lance as champion:
UPDATE bosses SET boss = 'Lance'   WHERE boss = 'Johto Champion'  AND version IN ('HeartGold','SoulSilver','BothHGSS');
-- If Lance was stored as 'Indigo Plateau' for HGSS, fix that too:
UPDATE bosses SET boss = 'Lance'   WHERE boss = 'Indigo Plateau'  AND version IN ('HeartGold','SoulSilver','BothHGSS');

-- Red (final boss)
UPDATE bosses SET boss = 'Red'     WHERE boss = 'Mt. Silver'      AND version IN ('HeartGold','SoulSilver','BothHGSS');
UPDATE bosses SET boss = 'Red'     WHERE boss = 'Mount Silver'    AND version IN ('HeartGold','SoulSilver','BothHGSS');

-- Verify result — run this after to confirm all HGSS boss names look correct:
-- SELECT DISTINCT boss, version FROM bosses WHERE version IN ('HeartGold','SoulSilver','BothHGSS') ORDER BY boss;
