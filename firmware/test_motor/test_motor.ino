/*
  Prueba de giro del motor paso a paso Minebea 17PM-K374BN02CN
  Driver: A4988 (HR4988)  |  Placa: ESP32 TTGO T-Call V1.4

  Pines:
    GPIO18 -> STEP
    GPIO19 -> DIR
    GPIO25 -> ENABLE (opcional, activo en LOW)

  Comportamiento: gira 2 vueltas en un sentido, pausa, gira 2 vueltas al
  otro sentido, apaga el driver unos segundos y repite.
  Usa una rampa de velocidad suave (arranque y frenado) para que el motor
  no pierda pasos. No necesita librerias externas.
*/

// ----- Pines -----
#define PIN_STEP 18
#define PIN_DIR  19
#define PIN_EN 25   // antes 32 (DTR del SIM800L)

// ----- Configuracion del motor y del driver -----
const bool USE_ENABLE = true;       // false si el cable de ENABLE no esta soldado
const int  STEPS_PER_REV = 200;     // motor de 1.8 grados
const int  MICROSTEPS = 16;         // 16 si MS1, MS2 y MS3 estan a 3V3. 1 si estan sin conectar

// ----- Parametros de la prueba (empezar suave) -----
const float START_RPS = 0.2;        // vueltas por segundo al arrancar y frenar
const float MAX_RPS   = 0.8;        // vueltas por segundo en crucero
const float REVS_PER_MOVE = 2.0;    // vueltas por movimiento
const float RAMP_REVS = 0.5;        // vueltas que dura cada rampa
const unsigned long PAUSE_MS = 1000;   // pausa entre sentidos
const unsigned long REST_MS  = 2000;   // descanso con el driver apagado

const long STEPS_PER_TURN = (long)STEPS_PER_REV * MICROSTEPS;

void stepPulse(unsigned int halfPeriodUs) {
  digitalWrite(PIN_STEP, HIGH);
  delayMicroseconds(halfPeriodUs);
  digitalWrite(PIN_STEP, LOW);
  delayMicroseconds(halfPeriodUs);
}

// Mueve un numero de pasos con rampa lineal de velocidad.
void moveSteps(long steps, bool directionA) {
  digitalWrite(PIN_DIR, directionA ? HIGH : LOW);
  delayMicroseconds(20);

  long rampSteps = (long)(RAMP_REVS * STEPS_PER_TURN);
  if (rampSteps * 2 > steps) rampSteps = steps / 2;
  if (rampSteps < 1) rampSteps = 1;

  for (long i = 0; i < steps; i++) {
    long d = (i < steps - i) ? i : (steps - i);   // distancia al inicio o al final
    if (d > rampSteps) d = rampSteps;

    float rps = START_RPS + (MAX_RPS - START_RPS) * (float)d / (float)rampSteps;
    float stepsPerSec = rps * (float)STEPS_PER_TURN;
    unsigned int halfUs = (unsigned int)(500000.0f / stepsPerSec);
    stepPulse(halfUs);
  }
}

void driverEnable(bool on) {
  if (USE_ENABLE) digitalWrite(PIN_EN, on ? LOW : HIGH);   // ENABLE es activo en LOW
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_STEP, OUTPUT);
  pinMode(PIN_DIR, OUTPUT);
  digitalWrite(PIN_STEP, LOW);
  digitalWrite(PIN_DIR, LOW);
  if (USE_ENABLE) {
    pinMode(PIN_EN, OUTPUT);
    driverEnable(false);
  }
  delay(500);
  Serial.println();
  Serial.println("Prueba de motor lista");
  Serial.print("Pasos por vuelta: ");
  Serial.println(STEPS_PER_TURN);
}

void loop() {
  long steps = (long)(REVS_PER_MOVE * STEPS_PER_TURN);

  driverEnable(true);
  delay(50);

  Serial.println("Sentido A");
  moveSteps(steps, true);
  delay(PAUSE_MS);

  Serial.println("Sentido B");
  moveSteps(steps, false);

  driverEnable(false);
  Serial.println("Descanso (driver apagado)");
  delay(REST_MS);
}
