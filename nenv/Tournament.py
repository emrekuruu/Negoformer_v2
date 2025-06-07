import datetime
import os
import random
import shutil
import time
import warnings
from typing import Union, Set, List, Tuple, Optional
import asyncio
import numpy as np
import pandas as pd
from tqdm import tqdm
from nenv.Agent import AgentClass
from nenv.logger import AbstractLogger, LoggerClass
from nenv.OpponentModel import OpponentModelClass
from nenv.SessionManager import SessionManager
from nenv.utils import ExcelLog, TournamentProcessMonitor, open_folder


class Tournament:
    """
        This class conducts a tournament based on given settings.
    """
    agent_classes: Set[AgentClass]                 #: List of Agent classes
    loggers: List[AbstractLogger]                  #: List of Logger classes
    domains: List[str]                             #: List of domains
    estimators: Set[OpponentModelClass]            #: List of opponent models
    deadline_time: Optional[int]                    #: Time-based deadline in terms of seconds
    deadline_round: Optional[int]                   #: Round-based deadline in terms of number of rounds
    result_dir: str                                #: The directory where the result logs will be extracted
    seed: Optional[int]                             #: Random seed for whole tournament
    shuffle: bool                                  #: Whether the combinations will be shuffled, or not
    repeat: int                                    #: Number of repetition for each combination
    self_negotiation: bool                         #: Whether the agents negotiate with itself, or not
    tournament_process: TournamentProcessMonitor   #: Process monitor
    killed: bool                                   #: Whether the tournament process is killed, or not

    def __init__(self, agent_classes: Union[List[AgentClass], Set[AgentClass]],
                 domains: List[str],
                 logger_classes: Union[List[LoggerClass], Set[LoggerClass]],
                 estimator_classes: Union[List[OpponentModelClass], Set[OpponentModelClass]],
                 deadline_time: Optional[int],
                 deadline_round: Optional[int],
                 self_negotiation: bool = False,
                 repeat: int = 1,
                 result_dir: str = "results/",
                 seed: Optional[int] = None,
                 shuffle: bool = False
                 ):
        """
            This class conducts a negotiation tournament.

            :param agent_classes: List of agent classes (i.e., subclass of AbstractAgent class)
            :param domains: List of domains
            :param logger_classes: List of loggers classes (i.e., subclass of AbstractLogger class)
            :param estimator_classes: List of estimator classes (i.e, subclass of AbstractOpponentModel class)
            :param deadline_time: Time-based deadline in terms of seconds
            :param deadline_round: Round-based deadline in terms of number of rounds
            :param self_negotiation: Whether the agents negotiate with itself. *Default false*.
            :param repeat: Number of repetition for each combination. *Default 1*
            :param result_dir: The result directory that the tournament logs will be created. *Default 'results/'*
            :param seed: Setting seed for whole tournament. *Default None*.
            :param shuffle: Whether shuffle negotiation combinations. *Default False*
        """

        assert deadline_time is not None or deadline_round is not None, "No deadline type is specified."
        assert deadline_time is None or deadline_time > 0, "Deadline must be positive."
        assert deadline_round is None or deadline_round > 0, "Deadline must be positive."

        if repeat <= 0:
            warnings.warn("repeat is set to 1.")
            repeat = 1

        assert len(agent_classes) > 0, "Empty list of agent classes."
        assert len(domains) > 0, "Empty list of domains."

        self.agent_classes = agent_classes
        self.domains = domains
        self.estimators = estimator_classes
        self.deadline_time = deadline_time
        self.deadline_round = deadline_round
        self.loggers = [logger_class(result_dir) for logger_class in set(logger_classes)]
        self.result_dir = result_dir
        self.seed = seed
        self.repeat = repeat
        self.self_negotiation = self_negotiation
        self.shuffle = shuffle
        self.tournament_process = TournamentProcessMonitor()
        self.killed = False

    def run(self):
        """
            This method starts the tournament

            :return: Nothing
        """
        # Set seed
        if self.seed is not None:
            random.seed(self.seed)
            np.random.seed(self.seed)
            os.environ['PYTHONHASHSEED'] = str(self.seed)


        os.makedirs(self.result_dir, exist_ok=True)
        os.makedirs(os.path.join(os.path.join(self.result_dir, "sessions/")), exist_ok=True)

        # Set killed flag
        self.killed = False

        # Extract domain information into the result directory
        self.extract_domains()

        # Get all combinations
        negotiations = self.generate_combinations()

        # Names for logger
        agent_names = []
        estimator_names = []

        # Tournament log file
        tournament_logs = ExcelLog(["TournamentResults", "UtilityDist"])

        tournament_logs.save(os.path.join(self.result_dir, "results.xlsx"))

        self.tournament_process.initiate(len(negotiations))

        print(f'Started at {str(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))}.')
        print("Total negotiation:", len(negotiations))

        indexed_files = pd.read_csv(os.path.join(os.path.dirname(os.path.dirname(__file__)), "indexed_files.csv"))

        print("*" * 50)

        for i, (agent_class_1, agent_class_2, domain_name) in enumerate(negotiations):
            # Start session
            session_runner = SessionManager(agent_class_1, agent_class_2, domain_name, self.deadline_time, self.deadline_round, list(self.estimators), self.loggers)

            session_path = "%s_%s_Domain%s.xlsx" % \
                           (session_runner.agentA.name, session_runner.agentB.name, domain_name)

            if session_path in indexed_files["relative_path"].values:
                print(f"Session {session_path} already exists. Skipping...")
                continue

            session_start_time = time.time()
            session_data = session_runner.run(os.path.join(self.result_dir, "sessions/", session_path))
            session_end_time = time.time()

            # Update total elapsed time
            session_elapsed_time = session_end_time - session_start_time

            # Get list of name for loggers
            if len(estimator_names) == 0:
                estimator_names = [estimator.name for estimator in session_runner.agentA.estimators]

            if session_runner.agentA.name not in agent_names:
                agent_names.append(session_runner.agentA.name)

            if session_runner.agentB.name not in agent_names:
                agent_names.append(session_runner.agentB.name)

            print(self.tournament_process.update(f"{session_runner.agentA.name} vs. {session_runner.agentB.name } in Domain: {domain_name}", session_elapsed_time))

            if self.killed:  # Check for kill signal
                return

            # Calculate tournament result from session data
            tournament_result = calculate_tournament_result_from_session(session_data, session_runner.agentA.name, session_runner.agentB.name, domain_name)
            
            if tournament_result is None:
                print(f"Warning: Could not process session data from {session_path}")
                continue
            
            # Simulate logger data from session
            logger_data = simulate_logger_data_from_session(session_data, tournament_result)
            
            # Add to tournament logs (both tournament results and logger data)
            log_entry = {"TournamentResults": tournament_result}
            log_entry.update(logger_data)
            tournament_logs.append(log_entry)

        self.tournament_process.end()
        print("*" * 50)
        print("Tournament has been done. Please, wait for analysis...")

        # Backup
        tournament_logs.save(os.path.join(self.result_dir, "results_backup.xlsx"))

        # On tournament end
        for logger in self.loggers:
            logger.on_tournament_end(tournament_logs, agent_names, self.domains, estimator_names)

        # Save tournament logs
        tournament_logs.save(os.path.join(self.result_dir, "results.xlsx"))

        print("Analysis have been completed.")
        print("*" * 50)

        print("Total Elapsed Time:", str(self.tournament_process.close()))

        # Show folder
        open_folder(self.result_dir)

    def generate_combinations(self) -> List[Tuple[AgentClass, AgentClass, str]]:
        """
            This method generates all combinations of negotiations.

            :return: Nothing
        """
        combinations = []

        for domain in self.domains:
            for agent_class_1 in self.agent_classes:
                for agent_class_2 in self.agent_classes:
                    if not self.self_negotiation and agent_class_1.__name__ == agent_class_2.__name__:
                        continue

                    for i in range(self.repeat):
                        combinations.append((agent_class_1, agent_class_2, domain))

        if self.shuffle:
            random.shuffle(combinations)

        return combinations

    def extract_domains(self):
        """
            This method extracts the domain information into the result directory.

            :return: Nothing
        """
        full_domains = pd.read_excel("domains/domains.xlsx", sheet_name="domains")

        domains = pd.DataFrame(columns=full_domains.columns[1:])

        domain_counter = 0

        for i, row in full_domains.iterrows():
            if str(row["DomainName"]) in self.domains:
                domains.loc[domain_counter] = row

                domain_counter += 1

        domains.to_excel(os.path.join(self.result_dir, "domains.xlsx"), sheet_name="domains", index=False)

    async def generate_results_from_existing_sessions(self):
        """
            This method generates results and summaries from existing session logs
            without re-running the tournament sessions using async processing.

            :return: Nothing
        """
        
        # Ensure result directory exists
        os.makedirs(self.result_dir, exist_ok=True)
        
        # Check if sessions directory exists
        sessions_dir = os.path.join(self.result_dir, "sessions/")
        if not os.path.exists(sessions_dir):
            raise FileNotFoundError(f"Sessions directory not found: {sessions_dir}")
        
        # Get all session files
        session_files = [f for f in os.listdir(sessions_dir) if f.endswith('.xlsx')]
        
        if not session_files:
            raise FileNotFoundError("No session files found in the sessions directory")
        
        print(f'Generating results from {len(session_files)} existing session files...')
        print("*" * 50)
        
        # Tournament log file
        tournament_logs = ExcelLog(["TournamentResults", "UtilityDist"])
        
        # Names for logger
        agent_names = []
        estimator_names = []
        
        # Create semaphore to limit concurrent operations
        semaphore = asyncio.Semaphore(20)  # Process 20 files concurrently
        
        def extract_agent_names_from_filename(filename):
            """Extract agent names from filename format: AgentA_AgentB_DomainX.xlsx"""
            name_without_ext = filename.replace('.xlsx', '')
            # Remove the Domain part from the end
            import re
            domain_match = re.search(r'_Domain\d+$', name_without_ext)
            if domain_match:
                name_without_domain = name_without_ext[:domain_match.start()]
                # Split into agent names (assuming format AgentA_AgentB)
                parts = name_without_domain.split('_')
                if len(parts) >= 2:
                    # Find the split point - typically the second agent starts with a capital letter
                    # or use a known pattern
                    agent_a = parts[0]
                    agent_b = '_'.join(parts[1:])
                    return agent_a, agent_b
            return None, None
        
        def calculate_tournament_result_from_session(session_data, agent_a, agent_b, domain_name):
            """Calculate tournament result from round-by-round session data"""
            if len(session_data) == 0:
                return None
                
            # Get the last row to determine final state
            last_row = session_data.iloc[-1]
            
            # Determine result type
            result = "Failed"  # Default
            who = "-"
            final_bid = None
            
            if last_row["Action"] == "Accept":
                result = "Acceptance" 
                who = last_row["Who"]
                final_bid = last_row["BidContent"]
            
            # Count number of offers (exclude Accept actions)
            num_offers = len(session_data[session_data["Action"] == "Offer"])
            
            # Create tournament result
            tournament_result = {
                "AgentA": agent_a,
                "AgentB": agent_b,
                "Round": int(last_row["Round"]),
                "Time": float(last_row["Time"]),
                "NumOffer": num_offers,
                "Who": who,
                "Result": result,
                "AgentAUtility": float(last_row["AgentAUtility"]),
                "AgentBUtility": float(last_row["AgentBUtility"]),
                "ProductScore": float(last_row["ProductScore"]),
                "SocialWelfare": float(last_row["SocialWelfare"]),
                "BidContent": final_bid,
                "ElapsedTime": float(last_row["ElapsedTime"]),
                "DomainName": domain_name,
                # Add additional fields that might be needed
                "NashDistance": float(last_row.get("NashDistance", 0)),
                "KalaiDistance": float(last_row.get("KalaiDistance", 0))
            }
            
            return tournament_result
        
        def simulate_logger_data_from_session(session_data, tournament_result):
            """Simulate logger data creation from session data"""
            logger_data = {}
            
            # Simulate UtilityDistributionLogger.on_session_end()
            utility_a, utility_b = [], []
            opp_utility_a, opp_utility_b = [], []

            for _, log_row in session_data.iterrows():
                if log_row["Action"] != "Offer":
                    continue

                if log_row["Who"] == 'A':
                    utility_a.append(float(log_row["AgentAUtility"]))
                    opp_utility_a.append(float(log_row["AgentBUtility"]))
                else:
                    utility_b.append(float(log_row["AgentBUtility"]))
                    opp_utility_b.append(float(log_row["AgentAUtility"]))

            utility_dist_data = {
                "MeanAgentUtilityA": np.mean(utility_a) if len(utility_a) > 0 else 0.,
                "MeanAgentUtilityB": np.mean(utility_b) if len(utility_b) > 0 else 0.,
                "MeanOpponentUtilityA": np.mean(opp_utility_a) if len(opp_utility_a) > 0 else 0.,
                "MeanOpponentUtilityB": np.mean(opp_utility_b) if len(opp_utility_b) > 0 else 0.,
                "StdAgentUtilityA": np.std(utility_a) if len(utility_a) > 0 else 0.,
                "StdAgentUtilityB": np.std(utility_b) if len(utility_b) > 0 else 0.,
                "StdOpponentUtilityA": np.std(opp_utility_a) if len(opp_utility_a) > 0 else 0.,
                "StdOpponentUtilityB": np.std(opp_utility_b) if len(opp_utility_b) > 0 else 0.,
                "MaxAgentUtilityA": np.max(utility_a) if len(utility_a) > 0 else 0.,
                "MaxAgentUtilityB": np.max(utility_b) if len(utility_b) > 0 else 0.,
                "MaxOpponentUtilityA": np.max(opp_utility_a) if len(opp_utility_a) > 0 else 0.,
                "MaxOpponentUtilityB": np.max(opp_utility_b) if len(opp_utility_b) > 0 else 0.,
                "MinAgentUtilityA": np.min(utility_a) if len(utility_a) > 0 else 0.,
                "MinAgentUtilityB": np.min(utility_b) if len(utility_b) > 0 else 0.,
                "MinOpponentUtilityA": np.min(opp_utility_a) if len(opp_utility_a) > 0 else 0.,
                "MinOpponentUtilityB": np.min(opp_utility_b) if len(opp_utility_b) > 0 else 0.,
            }
            
            logger_data["UtilityDist"] = utility_dist_data
            
            return logger_data
        
        async def process_session_file(session_file):
            """Process a single session file asynchronously"""
            async with semaphore:
                session_path = os.path.join(sessions_dir, session_file)
                
                try:
                    # Run pandas operation in thread pool
                    loop = asyncio.get_event_loop()
                    session_data = await loop.run_in_executor(None, pd.read_excel, session_path, "Session")
                    
                    # Extract agent names from filename
                    agent_a, agent_b = extract_agent_names_from_filename(session_file)
                    if agent_a is None or agent_b is None:
                        return None, f"Could not extract agent names from {session_file}"
                    
                    # Extract domain name from filename
                    import re
                    domain_match = re.search(r'Domain(\d+)', session_file)
                    domain_name = domain_match.group(1) if domain_match else "Unknown"
                    
                    # Calculate tournament result from session data
                    tournament_result = calculate_tournament_result_from_session(session_data, agent_a, agent_b, domain_name)
                    
                    if tournament_result is None:
                        return None, f"Could not process session data from {session_file}"
                    
                    # Simulate logger data from session
                    logger_data = simulate_logger_data_from_session(session_data, tournament_result)
                    
                    # Create log entry
                    log_entry = {"TournamentResults": tournament_result}
                    log_entry.update(logger_data)
                    
                    return (log_entry, agent_a, agent_b), None
                    
                except Exception as e:
                    return None, f"Could not load session file {session_file}: {str(e)}"
        
        # Process all files with progress bar
        print("Processing session files...")
        tasks = [process_session_file(session_file) for session_file in session_files]
        
        # Process with tqdm progress bar
        results = []
        successful_loads = 0
        failed_loads = 0
        
        with tqdm(total=len(tasks), desc="Loading sessions", unit="file") as pbar:
            for coro in asyncio.as_completed(tasks):
                result, error = await coro
                results.append((result, error))
                pbar.update(1)
                
                if result is not None:
                    successful_loads += 1
                else:
                    failed_loads += 1
        
        # Process results and collect data
        for result, error in results:
            if result is None:
                if error:
                    print(f"Warning: {error}")
                continue
                
            log_entry, agent_a, agent_b = result
            tournament_logs.append(log_entry)
            
            # Collect agent names
            if agent_a and agent_a not in agent_names:
                agent_names.append(agent_a)
            
            if agent_b and agent_b not in agent_names:
                agent_names.append(agent_b)
        
        print(f"Successfully loaded: {successful_loads} files")
        if failed_loads > 0:
            print(f"Failed to load: {failed_loads} files")
        
        # Extract estimator names (use the tournament config)
        estimator_names = [estimator.name for estimator in self.estimators]
        
        print("*" * 50)
        print("All sessions loaded. Running analysis...")
        
        # Backup
        tournament_logs.save(os.path.join(self.result_dir, "results_backup.xlsx"))
        
        # On tournament end - this is where the actual analysis happens
        for logger in self.loggers:
            logger.on_tournament_end(tournament_logs, agent_names, self.domains, estimator_names)
        
        # Save tournament logs
        tournament_logs.save(os.path.join(self.result_dir, "results.xlsx"))
        
        print("Analysis completed successfully.")
        print("*" * 50)
        
        # Show folder
        open_folder(self.result_dir)

    def generate_results_from_existing_sessions_sync(self):
        """
            Synchronous wrapper for generate_results_from_existing_sessions.
            This method can be called from synchronous code.

            :return: Nothing
        """
        asyncio.run(self.generate_results_from_existing_sessions())
