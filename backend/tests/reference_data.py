"""Small public reference datasets with published results.

The expected numbers quoted in the tests are the standard outputs of R
(t.test, aov, TukeyHSD, kruskal.test, oneway.test, lm, glm) for these datasets,
so they check the engine against an independent implementation.
"""
import pandas as pd

# Student's sleep data (R: datasets::sleep) - extra hours of sleep on two drugs
SLEEP_1 = [0.7, -1.6, -0.2, -1.2, -0.1, 3.4, 3.7, 0.8, 0.0, 2.0]
SLEEP_2 = [1.9, 0.8, 1.1, 0.1, -0.1, 4.4, 5.5, 1.6, 4.6, 3.4]

# R: datasets::PlantGrowth
PLANT = {
    "ctrl": [4.17, 5.58, 5.18, 6.11, 4.50, 4.61, 5.17, 4.53, 5.33, 5.14],
    "trt1": [4.81, 4.17, 4.41, 3.59, 5.87, 3.83, 6.03, 4.89, 4.32, 4.69],
    "trt2": [6.31, 5.12, 5.54, 5.50, 5.37, 5.29, 4.92, 6.15, 5.80, 5.26],
}

# Anscombe's quartet, set I
ANSCOMBE_X = [10, 8, 13, 9, 11, 14, 6, 4, 12, 7, 5]
ANSCOMBE_Y = [8.04, 6.95, 7.58, 8.81, 8.33, 9.96, 7.24, 4.26, 10.84, 4.82, 5.68]

# R: datasets::mtcars (four columns)
MTCARS = pd.DataFrame({
    "mpg": [21.0, 21.0, 22.8, 21.4, 18.7, 18.1, 14.3, 24.4, 22.8, 19.2, 17.8, 16.4, 17.3, 15.2, 10.4, 10.4, 14.7, 32.4, 30.4, 33.9,
            21.5, 15.5, 15.2, 13.3, 19.2, 27.3, 26.0, 30.4, 15.8, 19.7, 15.0, 21.4],
    "wt": [2.620, 2.875, 2.320, 3.215, 3.440, 3.460, 3.570, 3.190, 3.150, 3.440, 3.440, 4.070, 3.730, 3.780, 5.250, 5.424, 5.345,
           2.200, 1.615, 1.835, 2.465, 3.520, 3.435, 3.840, 3.845, 1.935, 2.140, 1.513, 3.170, 2.770, 3.570, 2.780],
    "hp": [110, 110, 93, 110, 175, 105, 245, 62, 95, 123, 123, 180, 180, 180, 205, 215, 230, 66, 52, 65, 97, 150, 150, 245, 175,
           66, 91, 113, 264, 175, 335, 109],
    "am": [1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1],
})
MTCARS_SCHEMA = {
    "mpg": {"type": "numeric", "measurement_level": "ratio"},
    "wt": {"type": "numeric", "measurement_level": "ratio"},
    "hp": {"type": "integer", "measurement_level": "ratio"},
    "am": {"type": "integer", "measurement_level": "nominal"},
}


def sleep_long() -> pd.DataFrame:
    return pd.DataFrame({"extra": SLEEP_1 + SLEEP_2, "drug": ["1"] * 10 + ["2"] * 10})


def sleep_wide() -> pd.DataFrame:
    return pd.DataFrame({"drug1": SLEEP_1, "drug2": SLEEP_2})


def plant_long() -> pd.DataFrame:
    return pd.DataFrame({"weight": sum(PLANT.values(), []), "group": sum(([k] * 10 for k in PLANT), [])})
