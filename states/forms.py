from aiogram.fsm.state import State, StatesGroup


class RegistrationStates(StatesGroup):
    waiting_referral_code = State()


class SubscriptionStates(StatesGroup):
    waiting_payment_confirm = State()
    waiting_sc_choice = State()


class ProfileStates(StatesGroup):
    waiting_branch_choice = State()
    waiting_mentor_code_input = State()


class QuestStates(StatesGroup):
    waiting_photo = State()
    waiting_quiz_answer = State()
    waiting_p2p_vote = State()


class AdminStates(StatesGroup):
    waiting_broadcast_text = State()
    waiting_control_photo = State()
    waiting_quiz_question = State()
    waiting_quiz_options = State()
    waiting_quiz_date = State()
    waiting_setting_key = State()
    waiting_setting_value = State()
    waiting_subscription_price = State()
