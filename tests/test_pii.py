from __future__ import annotations

from pulse.pii import find_pii, looks_like_name


def test_email_positive_and_negative() -> None:
    assert "email" in find_pii("please write to test.user@gmail.com about this delay")
    assert "email" not in find_pii("the app support chat never replies to tickets now")


def test_phone_positive_and_negative() -> None:
    assert "phone" in find_pii("call me on +91 98765 43210 because withdrawals are stuck")
    assert "phone" not in find_pii("it takes 3 days to withdraw money from here now")


def test_pan_positive_and_negative() -> None:
    assert "pan" in find_pii("my PAN is ABCDE1234F please check the account today")
    assert "pan" not in find_pii("please check my KYC status on the app again today")


def test_upi_positive_and_negative() -> None:
    assert "upi" in find_pii("send the refund to rahul@okaxis today if you can")
    assert "upi" not in find_pii("UPI payments fail every morning during market hours now")


def test_digit_run_positive_and_negative() -> None:
    assert "digit_run" in find_pii("order 12345678 is still pending from last week now")
    assert "digit_run" not in find_pii("it has been pending for 7 days now already here")


def test_handle_positive_and_negative() -> None:
    assert "handle" in find_pii("follow me @traderrahul for more on this issue today")
    assert "handle" not in find_pii("the app crashes after the latest update every day")


def test_self_id_positive_and_negative() -> None:
    assert "self_id" in find_pii("my name is Priya and this app is slow after updates")
    assert "self_id" not in find_pii("the name of the fund is wrong in reports today")


def test_looks_like_name_catches_mid_sentence_full_name() -> None:
    text = "The app is slow and Rahul Sharma never got a reply from support this week"
    assert looks_like_name(text)


def test_looks_like_name_catches_start_pattern() -> None:
    assert looks_like_name("Priya here, withdrawals take three days after I sell shares")
    assert looks_like_name("Amit Kumar: the charts freeze whenever the market opens today")


def test_looks_like_name_catches_end_signature_and_sign_off() -> None:
    assert looks_like_name("Withdrawals take three days after I sell my shares Yogeshwara m p")
    assert looks_like_name("Withdrawals take three days after I sell my shares. Thanks, Priya")


def test_looks_like_name_ignores_products_sentence_start_and_plain_thanks() -> None:
    assert not looks_like_name("I have used Groww for two years and the charts freeze after opening")
    assert not looks_like_name("Mutual Funds on this app take too long to redeem after selling")
    assert not looks_like_name("Withdrawals take three days after I sell my shares on this app")
    assert not looks_like_name("The withdrawals take three days after I sell shares. Thanks")
