# Recidiviz - a data platform for criminal justice reform
# Copyright (C) 2021 Recidiviz, Inc.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
# =============================================================================
"""SuperSimulation composed object for outputting simulation results."""
from typing import Dict, List, Optional, Tuple

import pandas as pd

from super_simulation.time_converter import TimeConverter
from utils import bq_utils


class Exporter:
    """Manage model exports from SuperSimulation."""

    def __init__(
        self,
        microsim: bool,
        compartment_costs: Dict[str, float],
        simulation_tag: str,
        time_converter: TimeConverter,
    ):
        self.microsim = microsim
        self.compartment_costs = compartment_costs
        self.simulation_tag = simulation_tag
        self.time_converter = time_converter

    def upload_baseline_simulation_results_to_bq(
        self,
        project_id: str,
        simulation_tag: Optional[str],
        output_population_data: pd.DataFrame,
        output_outflows_data: pd.DataFrame,
        excluded_pop: pd.DataFrame,
        total_pop: pd.DataFrame,
    ) -> Dict[str, pd.DataFrame]:
        """Format then upload baseline simulation results to Big Query."""

        microsim_population_df = output_population_data.copy()
        microsim_outflows_df = output_outflows_data.copy()
        for df in [microsim_population_df, microsim_outflows_df]:
            if "time_step" in df.columns:
                df["year"] = self.time_converter.convert_time_steps_to_year(
                    df["time_step"]
                )
                df.drop("time_step", axis=1, inplace=True)
        if not excluded_pop.empty:
            microsim_population_df = self._prep_for_upload(
                microsim_population_df, excluded_pop, total_pop
            )

        bq_utils.upload_baseline_simulation_results(
            project_id,
            microsim_population_df,
            microsim_outflows_df,
            simulation_tag if simulation_tag else self.simulation_tag,
        )
        return {
            "baseline_output_data": microsim_population_df,
            "baseline_transition_data": microsim_outflows_df,
        }

    def upload_policy_simulation_results_to_bq(
        self,
        project_id: str,
        simulation_tag: Optional[str],
        output_data: Dict[str, pd.DataFrame],
        cost_multipliers: pd.DataFrame,
    ) -> Dict[str, pd.DataFrame]:
        """Format then upload policy simulation results to Big Query."""
        # TODO(#6633): incorporate excluded populations into policy simulation upload for microsimulations
        (
            spending_diff,
            compartment_life_years_diff,
            spending_diff_non_cumulative,
        ) = self._get_output_metrics(
            output_data["policy_simulation"],
            cost_multipliers,
        )
        aggregate_output_data = (
            output_data["policy_simulation"]
            .reset_index(drop=False)
            .groupby(["year", "compartment"])[
                ["policy_compartment_population", "control_compartment_population"]
            ]
            .sum()
            .reset_index()
        )
        aggregate_output_data.index = aggregate_output_data.year
        bq_utils.upload_policy_simulation_results(
            project_id,
            simulation_tag if simulation_tag else self.simulation_tag,
            spending_diff,
            compartment_life_years_diff,
            aggregate_output_data,
            spending_diff_non_cumulative,
        )
        return {
            "spending_diff": spending_diff,
            "compartment_life_years_diff": compartment_life_years_diff,
            "spending_diff_non_cumulative": spending_diff_non_cumulative,
            "population_diff": aggregate_output_data,
        }

    def upload_validation_projection_results_to_bq(
        self,
        project_id: str,
        simulation_tag: Optional[str],
        validation_projections_data: pd.DataFrame,
    ) -> None:
        if "time_step" in validation_projections_data.columns:
            validation_projections_data[
                "year"
            ] = self.time_converter.convert_time_steps_to_year(
                validation_projections_data["time_step"]
            )
            validation_projections_data.drop("time_step", axis=1, inplace=True)

        bq_utils.upload_validation_projection_results(
            project_id,
            validation_projections_data,
            simulation_tag if simulation_tag else self.simulation_tag,
        )

    @classmethod
    def _prep_for_upload(
        cls,
        projection_data: pd.DataFrame,
        excluded_pop: pd.DataFrame,
        total_pop: pd.DataFrame,
    ) -> pd.DataFrame:
        """function for scaling and any other state-specific operations required pre-upload"""

        scalar_dict = cls._calculate_prep_scale_factor(excluded_pop, total_pop)
        print(scalar_dict)

        output_data = projection_data.copy()
        output_data["scale_factor"] = output_data.compartment.map(scalar_dict).fillna(1)

        error_scale_factors = output_data[output_data["scale_factor"] == 0]
        if not error_scale_factors.empty:
            raise ValueError(
                f"The scale factor cannot be 0 for the population scaling: {error_scale_factors}"
            )

        scaling_columns = [
            "compartment_population",
            "compartment_population_min",
            "compartment_population_max",
        ]
        output_data.loc[:, scaling_columns] = output_data.loc[
            :, scaling_columns
        ].multiply(output_data.loc[:, "scale_factor"], axis="index")
        output_data = output_data.drop("scale_factor", axis=1)

        return output_data

    @classmethod
    def _calculate_prep_scale_factor(
        cls,
        excluded_pop: pd.DataFrame,
        total_pop: pd.DataFrame,
    ) -> Dict[str, float]:
        """Compute the scale factor per compartment by calculating the fraction of the initial total population
        that should have been excluded.
        """
        # Make sure there is only one row per compartment
        if excluded_pop["compartment"].nunique() != len(excluded_pop["compartment"]):
            raise ValueError(
                f"Excluded population has duplicate rows for compartments: {excluded_pop}"
            )

        # Calculate the scale factor for each compartment that is in the `excluded_pop`
        # by dividing the total excluded pop by the total pop on the `run_date`
        scale_factors = {}
        for _index, row in excluded_pop.iterrows():
            # TODO(#9720): make this more generalized/customizable for other states
            if row.compartment == "INCARCERATION - ALL":
                compartment_pop = total_pop[
                    total_pop.compartment.isin(
                        [
                            "INCARCERATION - GENERAL",
                            "INCARCERATION - RE-INCARCERATION",
                            "INCARCERATION - TREATMENT_IN_PRISON",
                            "INCARCERATION - PAROLE_BOARD_HOLD",
                        ]
                    )
                ].compartment_population.sum()
            elif row.compartment == "INCARCERATION - GENERAL":
                compartment_pop = total_pop[
                    total_pop.compartment.isin(
                        [
                            "INCARCERATION - GENERAL",
                            "INCARCERATION - RE-INCARCERATION",
                        ]
                    )
                ].compartment_population.sum()
                excluded_general_pop = excluded_pop = excluded_pop[
                    excluded_pop.compartment.isin(
                        [
                            "INCARCERATION - GENERAL",
                            "INCARCERATION - RE-INCARCERATION",
                        ]
                    )
                ].compartment_population.sum()
                scale_factors[row.compartment] = (
                    1 - excluded_general_pop / compartment_pop
                )
                continue
            elif row.compartment == "SUPERVISION - ALL":
                compartment_pop = total_pop[
                    total_pop.compartment.isin(
                        ["SUPERVISION - PROBATION", "SUPERVISION - PAROLE"]
                    )
                ].compartment_population.sum()
            elif row.compartment == "SUPERVISION - INTERNAL_UNKNOWN":
                compartment_pop = row.compartment_population
            else:
                compartment_pop = total_pop[
                    total_pop.compartment == row.compartment
                ].compartment_population.sum()

            if compartment_pop == 0:
                raise ValueError(f"Population for {row.compartment} cannot be 0")
            scale_factors[row.compartment] = (
                1 - row.compartment_population / compartment_pop
            )

        return scale_factors

    def _get_output_metrics(
        self,
        formatted_simulation_results: pd.DataFrame,
        cost_multipliers: pd.DataFrame,
    ) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """
        Generates savings and life-years saved; helper function for simulate_policy()
        `cost_multipliers` should be a df of how to scale the per_year_cost for each subgroup
        """
        compartment_life_years_diff = pd.DataFrame()
        spending_diff_non_cumulative = pd.DataFrame()
        spending_diff = pd.DataFrame()

        simulation_groups = list(
            formatted_simulation_results["simulation_group"].unique()
        )

        cost_multipliers = self._get_complete_cost_multipliers(
            cost_multipliers, simulation_groups
        )

        # go through and calculate differences for each subgroup
        for subgroup_tag in simulation_groups:
            subgroup_data = formatted_simulation_results[
                formatted_simulation_results["simulation_group"] == subgroup_tag
            ]

            subgroup_life_years_diff = pd.DataFrame(
                index=subgroup_data.index.get_level_values("year").unique(),
                columns=subgroup_data.compartment.unique(),
            )

            for compartment_name, compartment_data in subgroup_data.groupby(
                "compartment"
            ):
                # Compute the population difference with integer values
                # so compartments with fractional population differences (less than 1)
                # do not indicate any cost changes
                subgroup_life_years_diff.loc[
                    compartment_data.index.get_level_values("year"), compartment_name
                ] = (
                    compartment_data["control_compartment_population"].astype(int)
                    - compartment_data["policy_compartment_population"].astype(int)
                ) * self.time_converter.get_time_step()

            subgroup_spending_diff_non_cumulative = (
                subgroup_life_years_diff.copy() / self.time_converter.get_time_step()
            )
            subgroup_life_years_diff = subgroup_life_years_diff.cumsum()
            subgroup_spending_diff = subgroup_life_years_diff.copy()

            # pull out cost multiplier for this subgroup
            multiplier = (
                cost_multipliers[cost_multipliers["simulation_group"] == subgroup_tag]
                .iloc[0]
                .multiplier
            )

            for compartment, cost in self.compartment_costs.items():
                subgroup_spending_diff[compartment] *= cost * multiplier
                subgroup_spending_diff_non_cumulative[compartment] *= cost * multiplier

            # add subgroup outputs to total outputs
            compartment_life_years_diff = compartment_life_years_diff.add(
                subgroup_life_years_diff, fill_value=0
            )
            spending_diff_non_cumulative = spending_diff_non_cumulative.add(
                subgroup_spending_diff_non_cumulative, fill_value=0
            )
            spending_diff = spending_diff.add(subgroup_spending_diff, fill_value=0)

        spending_diff.index.name = "year"
        compartment_life_years_diff.index.name = "year"
        spending_diff_non_cumulative.index.name = "year"

        return spending_diff, compartment_life_years_diff, spending_diff_non_cumulative

    @classmethod
    def _get_complete_cost_multipliers(
        cls,
        cost_multipliers: pd.DataFrame,
        simulation_groups: List[str],
    ) -> pd.DataFrame:
        """Gets the complete cost multipliers."""
        if cost_multipliers.empty:
            complete_cost_multipliers = pd.DataFrame(
                columns=["simulation_group", "multiplier"]
            )
        else:
            complete_cost_multipliers = cost_multipliers.copy()

        for simulation_group in simulation_groups:
            if simulation_group not in complete_cost_multipliers["simulation_group"]:
                complete_cost_multipliers = pd.concat(
                    [
                        complete_cost_multipliers,
                        pd.Series(
                            {"simulation_group": simulation_group, "multiplier": 1}
                        )
                        .to_frame()
                        .T,
                    ],
                    ignore_index=True,
                )
        return complete_cost_multipliers
