// Distribution adaptation: original hook entrypoints remain byte-identical.
// Node's verified built-in SQLite replaces optional native-addon repair.
import { DatabaseSync } from 'node:sqlite';
const database = new DatabaseSync(':memory:');
database.exec('CREATE VIRTUAL TABLE readiness USING fts5(value)');
database.close();
